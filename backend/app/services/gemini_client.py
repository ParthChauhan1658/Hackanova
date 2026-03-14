"""
GeminiClient — thin async wrapper around Gemini 2.0 Flash REST API.
Uses httpx.AsyncClient directly (no google-generativeai SDK).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.core.constants import GEMINI_MODEL, GEMINI_TIMEOUT_SECONDS
from app.models.assessment import RiskAssessment
from app.models.reasoning import (
    DecisionSource,
    DifferentialDiagnosis,
    LLMReasoning,
    RecommendedAction,
)
from app.models.vitals import ProcessedReading
from app.services.llm_prompts import build_claude_system_prompt, build_claude_user_prompt

logger = logging.getLogger(__name__)

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={api_key}"
)


class GeminiClient:
    """
    Calls the Gemini 2.0 Flash REST API.
    Raises on any error — LLMClient handles fallback.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout_seconds: float = GEMINI_TIMEOUT_SECONDS,
        model: str = GEMINI_MODEL,
    ) -> None:
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self._timeout = timeout_seconds
        self._model = model

    async def reason(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
    ) -> LLMReasoning:
        """
        Call Gemini and return LLMReasoning.
        Raises httpx.HTTPError or json.JSONDecodeError on failure.
        """
        system_prompt = build_claude_system_prompt()
        user_prompt   = build_claude_user_prompt(processed, assessment)

        url = _GEMINI_URL.format(model=self._model, api_key=self._api_key)
        payload = {
            "system_instruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
            },
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        content_text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(content_text)

        return self._build_reasoning(parsed, processed, assessment)

    def _build_reasoning(
        self,
        parsed: dict,
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
            decision_source=DecisionSource.LLM_GEMINI,
            shal_band=assessment.shal_band.value,
            final_score=assessment.final_score,
            thinking_chain=None,
            reasoning_summary=parsed.get("reasoning_summary", ""),
            differential_diagnoses=diagnoses,
            recommended_actions=actions,
            confidence=float(parsed.get("confidence", 0.6)),
            considered_and_discarded=parsed.get("considered_and_discarded", []),
            vitals_snapshot={k: v for k, v in processed.validated_vitals.items()},
            syndromes_fired=list(assessment.sl3.syndromes_fired),
            trends_fired=list(assessment.sl4.trends_fired),
            hard_override_type=assessment.hard_override_type,
            model_used=self._model,
            latency_ms=0.0,
            reasoned_at=now,
        )
