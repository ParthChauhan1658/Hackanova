"""
LLMClient — 3-tier reasoning chain orchestrator for SENTINEL.
Tier 1: Claude claude-sonnet-4-20250514 with extended thinking
Tier 2: Gemini 2.0 Flash (fallback)
Tier 3: Rule-based fallback (always available, < 5ms)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.core.constants import (
    CLAUDE_MAX_TOKENS,
    CLAUDE_MODEL,
    CLAUDE_THINKING_BUDGET_TOKENS,
    CLAUDE_TIMEOUT_SECONDS,
    LLM_CONFIDENCE_THRESHOLD,
    REASONING_HISTORY_KEY,
    REASONING_HISTORY_MAX,
    REASONING_LATEST_KEY,
)
from app.core.redis_client import RedisClient
from app.models.assessment import RiskAssessment, SHALBand
from app.models.reasoning import (
    DecisionSource,
    DifferentialDiagnosis,
    LLMReasoning,
    RecommendedAction,
)
from app.models.vitals import ProcessedReading
from app.services.gemini_client import GeminiClient
from app.services.llm_prompts import build_claude_system_prompt, build_claude_user_prompt
from app.services.rule_fallback import RuleFallback

logger = logging.getLogger(__name__)

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


class LLMClient:
    """
    3-tier LLM reasoning chain.
    Only invoked for HIGH or CRITICAL SHAL bands.
    """

    def __init__(
        self,
        redis_client: RedisClient,
        gemini_client: GeminiClient,
        rule_fallback: RuleFallback,
        claude_timeout_seconds: float = CLAUDE_TIMEOUT_SECONDS,
        confidence_threshold: float = LLM_CONFIDENCE_THRESHOLD,
        model: str = CLAUDE_MODEL,
    ) -> None:
        self.redis               = redis_client
        self.gemini              = gemini_client
        self.rule_fallback       = rule_fallback
        self.claude_timeout      = claude_timeout_seconds
        self.confidence_threshold = confidence_threshold
        self.model               = model

    async def reason(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
    ) -> LLMReasoning:
        """
        Run the 3-tier chain. Always returns a LLMReasoning — never raises.
        Tier 3 is the guaranteed safety floor.
        """
        # Invocation guard
        if assessment.shal_band not in (SHALBand.HIGH, SHALBand.CRITICAL):
            raise ValueError(
                f"LLMClient.reason() called for band {assessment.shal_band}. "
                f"Only HIGH and CRITICAL bands invoke the LLM. "
                f"This is a programming error — check pipeline.py."
            )

        start_time = time.monotonic()
        reasoning: Optional[LLMReasoning] = None

        # ── Tier 1 — Claude ───────────────────────────────────────────────────
        try:
            logger.info(
                "LLM Tier 1 (Claude) — patient %s band %s score %.1f",
                processed.original.patient_id,
                assessment.shal_band.value,
                assessment.final_score,
            )
            reasoning = await self._call_claude(processed, assessment)
        except Exception as exc:
            logger.warning("Claude tier failed unexpectedly: %s", exc)

        # ── Tier 2 — Gemini ───────────────────────────────────────────────────
        if reasoning is None:
            try:
                logger.info(
                    "LLM Tier 2 (Gemini) — Claude unavailable for patient %s",
                    processed.original.patient_id,
                )
                reasoning = await self._call_gemini(processed, assessment)
            except Exception as exc:
                logger.warning("Gemini tier failed unexpectedly: %s", exc)

        # ── Tier 3 — Rule fallback ─────────────────────────────────────────────
        if reasoning is None:
            logger.info(
                "LLM Tier 3 (Rule fallback) — both LLM tiers failed for patient %s",
                processed.original.patient_id,
            )
            reasoning = self._call_rule_fallback(processed, assessment)

        reasoning.latency_ms = (time.monotonic() - start_time) * 1000

        logger.info(
            "Reasoning complete: patient=%s source=%s confidence=%.2f latency=%.0fms",
            processed.original.patient_id,
            reasoning.decision_source.value,
            reasoning.confidence,
            reasoning.latency_ms,
        )

        await self._store_reasoning(reasoning)
        return reasoning

    # ── Tier 1 ─────────────────────────────────────────────────────────────────

    async def _call_claude(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
    ) -> Optional[LLMReasoning]:
        """
        Call Claude REST API with extended thinking.
        Returns None on timeout, HTTP error, or JSON parse failure.
        """
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set — skipping Claude tier")
            return None

        payload = {
            "model": self.model,
            "max_tokens": CLAUDE_MAX_TOKENS,
            "thinking": {
                "type": "enabled",
                "budget_tokens": CLAUDE_THINKING_BUDGET_TOKENS,
            },
            "temperature": 1,  # required when extended thinking is enabled
            "system": build_claude_system_prompt(),
            "messages": [
                {
                    "role": "user",
                    "content": build_claude_user_prompt(processed, assessment),
                }
            ],
        }

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "interleaved-thinking-2025-05-14",
        }

        try:
            async with httpx.AsyncClient(timeout=self.claude_timeout + 2) as client:
                response = await asyncio.wait_for(
                    client.post(_ANTHROPIC_URL, json=payload, headers=headers),
                    timeout=self.claude_timeout,
                )
            response.raise_for_status()
            data = response.json()
        except asyncio.TimeoutError:
            logger.warning(
                "Claude timed out after %.1fs — falling back to Gemini",
                self.claude_timeout,
            )
            return None
        except httpx.HTTPStatusError as exc:
            logger.warning("Claude HTTP %s — falling back to Gemini", exc.response.status_code)
            return None
        except Exception as exc:
            logger.warning("Claude call error: %s — falling back to Gemini", exc)
            return None

        # Parse response
        try:
            content_blocks = data.get("content", [])
            thinking_blocks = [b for b in content_blocks if b.get("type") == "thinking"]
            text_blocks     = [b for b in content_blocks if b.get("type") == "text"]

            thinking_chain: Optional[str] = (
                thinking_blocks[0].get("thinking") if thinking_blocks else None
            )
            raw_json = text_blocks[0].get("text", "") if text_blocks else ""

            # Strip accidental markdown fences
            clean = raw_json.strip().removeprefix("```json").removesuffix("```").strip()
            if not clean:
                logger.warning("Claude returned empty text block")
                return None

            parsed = json.loads(clean)
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.warning("Claude response parse error: %s", exc)
            return None

        confidence = float(parsed.get("confidence", 0.0))

        # Low-confidence hand-off to rule fallback
        if confidence < self.confidence_threshold:
            logger.info(
                "Claude confidence %.2f below threshold %.2f — LLM_LOW_CONFIDENCE, "
                "handing off to rule engine",
                confidence,
                self.confidence_threshold,
            )
            fallback = self.rule_fallback.reason(processed, assessment)
            fallback.decision_source = DecisionSource.LLM_LOW_CONFIDENCE
            fallback.model_used = self.model
            return fallback

        return self._build_claude_reasoning(parsed, thinking_chain, processed, assessment)

    def _build_claude_reasoning(
        self,
        parsed: dict,
        thinking_chain: Optional[str],
        processed: ProcessedReading,
        assessment: RiskAssessment,
    ) -> LLMReasoning:
        now = datetime.now(timezone.utc)
        orig = processed.original

        diagnoses = [
            DifferentialDiagnosis(
                diagnosis=d.get("diagnosis", "Unknown"),
                probability=float(d.get("probability", 0.5)),
                supporting_evidence=d.get("supporting_evidence", []),
                against_evidence=d.get("against_evidence", []),
                clinical_source=d.get("clinical_source", ""),
            )
            for d in parsed.get("differential_diagnoses", [])
        ]

        actions = [
            RecommendedAction(
                action=a.get("action", ""),
                urgency=a.get("urgency", "MONITOR"),
                rationale=a.get("rationale", ""),
            )
            for a in parsed.get("recommended_actions", [])
        ]

        return LLMReasoning(
            patient_id=orig.patient_id,
            session_id=orig.session_id,
            reading_id=orig.reading_id,
            timestamp=orig.timestamp,
            decision_source=DecisionSource.LLM_CLAUDE,
            shal_band=assessment.shal_band.value,
            final_score=assessment.final_score,
            thinking_chain=thinking_chain,
            reasoning_summary=parsed.get("reasoning_summary", ""),
            differential_diagnoses=diagnoses,
            recommended_actions=actions,
            confidence=float(parsed.get("confidence", 0.7)),
            considered_and_discarded=parsed.get("considered_and_discarded", []),
            vitals_snapshot={k: v for k, v in processed.validated_vitals.items()},
            syndromes_fired=list(assessment.sl3.syndromes_fired),
            trends_fired=list(assessment.sl4.trends_fired),
            hard_override_type=assessment.hard_override_type,
            model_used=self.model,
            latency_ms=0.0,
            reasoned_at=now,
        )

    # ── Tier 2 ─────────────────────────────────────────────────────────────────

    async def _call_gemini(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
    ) -> Optional[LLMReasoning]:
        """
        Delegate to GeminiClient.
        Returns None on any error (caller handles fallback).
        """
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            logger.warning("GEMINI_API_KEY not set — skipping Gemini tier")
            return None
        try:
            return await self.gemini.reason(processed, assessment)
        except Exception as exc:
            logger.warning("Gemini tier error: %s", exc)
            return None

    # ── Tier 3 ─────────────────────────────────────────────────────────────────

    def _call_rule_fallback(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
    ) -> LLMReasoning:
        """
        Synchronous rule-based fallback. Never propagates exceptions.
        """
        try:
            return self.rule_fallback.reason(processed, assessment)
        except Exception as exc:
            logger.error("Rule fallback raised unexpectedly: %s", exc)
            # Absolute floor — minimal safe object
            now = datetime.now(timezone.utc)
            orig = processed.original
            return LLMReasoning(
                patient_id=orig.patient_id,
                session_id=orig.session_id,
                reading_id=orig.reading_id,
                timestamp=orig.timestamp,
                decision_source=DecisionSource.RULE_BASED,
                shal_band=assessment.shal_band.value,
                final_score=assessment.final_score,
                reasoning_summary=(
                    f"SENTINEL emergency fallback: score {assessment.final_score}/100 "
                    f"— manual review required."
                ),
                differential_diagnoses=[
                    DifferentialDiagnosis(
                        diagnosis="High-Risk Pattern — manual review required",
                        probability=0.50,
                        supporting_evidence=[],
                        against_evidence=[],
                        clinical_source="SENTINEL",
                    )
                ],
                recommended_actions=[
                    RecommendedAction(
                        action="Immediate manual clinical review",
                        urgency="IMMEDIATE",
                        rationale="Automated reasoning unavailable",
                    )
                ],
                confidence=0.50,
                considered_and_discarded=[],
                vitals_snapshot={},
                syndromes_fired=[],
                trends_fired=[],
                hard_override_type=assessment.hard_override_type,
                model_used=None,
                latency_ms=0.0,
                reasoned_at=now,
            )

    # ── Redis storage ──────────────────────────────────────────────────────────

    async def _store_reasoning(self, reasoning: LLMReasoning) -> None:
        """Store reasoning in Redis and publish to actions channel."""
        pid = reasoning.patient_id
        payload = reasoning.model_dump(mode="json")
        payload_str = json.dumps(payload, default=str)

        latest_key  = REASONING_LATEST_KEY.format(patient_id=pid)
        history_key = REASONING_HISTORY_KEY.format(patient_id=pid)

        try:
            client = await self.redis.get_client()
            await client.set(latest_key, payload_str)
            await client.lpush(history_key, payload_str)
            await client.ltrim(history_key, 0, REASONING_HISTORY_MAX - 1)
        except Exception as exc:
            logger.warning("Failed to store reasoning in Redis for %s: %s", pid, exc)

        top_diagnosis = (
            reasoning.differential_diagnoses[0].diagnosis
            if reasoning.differential_diagnoses
            else "Unknown"
        )

        await self.redis.publish_event(
            f"actions:{pid}",
            {
                "event": "REASONING_COMPLETE",
                "patient_id": pid,
                "shal_band": reasoning.shal_band,
                "final_score": reasoning.final_score,
                "decision_source": reasoning.decision_source.value,
                "reasoning_summary": reasoning.reasoning_summary,
                "confidence": reasoning.confidence,
                "top_diagnosis": top_diagnosis,
            },
        )
