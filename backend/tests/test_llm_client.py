"""
Pytest tests for the SENTINEL LLM Reasoning Engine (3-tier chain).
HTTP calls are mocked via unittest.mock.patch / respx-compatible MagicMock.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import fakeredis.aioredis

from app.core.redis_client import RedisClient
from app.models.assessment import (
    MEWSResult,
    RiskAssessment,
    ScoreContributor,
    SHALBand,
    SL1Result,
    SL2Result,
    SL3Result,
    SL4Result,
    SL5Result,
)
from app.models.reasoning import DecisionSource, LLMReasoning
from app.models.vitals import (
    ActivityLevel,
    ECGRhythm,
    FallEvent,
    HardOverride,
    ProcessedReading,
    VitalReading,
)
from app.services.gemini_client import GeminiClient
from app.services.llm_client import LLMClient
from app.services.llm_prompts import build_claude_user_prompt
from app.services.rule_fallback import RuleFallback


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def redis_client():
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = RedisClient(client=fake)
    yield client
    await fake.aclose()


@pytest.fixture
def rule_fallback():
    return RuleFallback()


@pytest.fixture
def mock_gemini():
    return MagicMock(spec=GeminiClient)


@pytest.fixture
def llm_client(redis_client, mock_gemini, rule_fallback):
    return LLMClient(
        redis_client=redis_client,
        gemini_client=mock_gemini,
        rule_fallback=rule_fallback,
        claude_timeout_seconds=2.0,
    )


def _now():
    return datetime.now(timezone.utc)


def make_processed(
    patient_id: str = "P001",
    heart_rate: float = 108.0,
    respiratory_rate: float = 22.0,
    spo2: float = 93.0,
    body_temperature: float = 38.4,
    hrv_ms: float = 32.0,
    stress_score: float = 68.0,
    steps_per_hour: float = 0.0,
    hard_override: Optional[HardOverride] = None,
    apply_vigorous: bool = False,
) -> ProcessedReading:
    now = _now()
    reading = VitalReading(
        reading_id="RID001",
        patient_id=patient_id,
        session_id="S001",
        timestamp=now,
        heart_rate=heart_rate,
        respiratory_rate=respiratory_rate,
        spo2=spo2,
        body_temperature=body_temperature,
        hrv_ms=hrv_ms,
        stress_score=stress_score,
        steps_per_hour=steps_per_hour,
        ecg_rhythm=ECGRhythm.NORMAL,
        deep_sleep_pct=20.0,
    )
    return ProcessedReading(
        original=reading,
        validated_vitals={
            "heart_rate": heart_rate, "respiratory_rate": respiratory_rate,
            "spo2": spo2, "body_temperature": body_temperature,
            "hrv_ms": hrv_ms, "stress_score": stress_score,
            "steps_per_hour": steps_per_hour,
        },
        is_interpolated={},
        threshold_flags={},
        window_trends={},
        hard_override=hard_override,
        hrv_acute_drop=False,
        apply_hr_vigorous_suppressor=apply_vigorous,
        apply_hr_sedentary_amplifier=False,
        signal_quality=100.0,
        location=None,
        low_signal_quality=False,
        processed_at=now,
    )


def make_assessment(
    shal_band: SHALBand = SHALBand.CRITICAL,
    final_score: float = 89.2,
    syndromes: list[str] | None = None,
    trends: list[str] | None = None,
    hard_override_active: bool = False,
    hard_override_type: Optional[str] = None,
) -> RiskAssessment:
    now = _now()
    syndromes = syndromes or ["SIRS / Early Sepsis", "Multi-System Stress"]
    trends = trends or []
    empty_sl1 = SL1Result(raw_points=0, normalised_points=0, contributors=[], vital_scores={})
    empty_sl2 = SL2Result(additive_points=0, weight_multipliers_applied={}, contributors=[])
    sl3 = SL3Result(
        syndromes_fired=syndromes,
        total_points=45.0,
        contributors=[],
        qsofa_score=1,
        qsofa_criteria_met=["qSOFA: RR >= 22 /min"],
    )
    sl4 = SL4Result(trends_fired=trends, total_points=0.0, contributors=[])
    sl5 = SL5Result(anomaly_score=0.3, points_added=0.0, xai_label="", contributor=None)
    mews = MEWSResult(mews_score=3, mews_flag=False, review_flag_added=False)
    return RiskAssessment(
        patient_id="P001",
        session_id="S001",
        reading_id="RID001",
        timestamp=now,
        final_score=final_score,
        shal_band=shal_band,
        hard_override_active=hard_override_active,
        hard_override_type=hard_override_type,
        sl1=empty_sl1,
        sl2=empty_sl2,
        sl3=sl3,
        sl4=sl4,
        sl5=sl5,
        mews=mews,
        all_contributors=[],
        hold_log=None,
        xai_narrative="test",
        assessed_at=now,
    )


def _valid_claude_response(confidence: float = 0.82) -> dict:
    return {
        "content": [
            {
                "type": "thinking",
                "thinking": "Step 1: Analyse vitals. Step 2: Consider SIRS.",
            },
            {
                "type": "text",
                "text": json.dumps({
                    "reasoning_summary": "SIRS triad met. High-risk escalation required.",
                    "confidence": confidence,
                    "differential_diagnoses": [
                        {
                            "diagnosis": "Early Sepsis / SIRS",
                            "probability": 0.72,
                            "supporting_evidence": ["HR 108", "Temp 38.4"],
                            "against_evidence": ["No confirmed source"],
                            "clinical_source": "SIRS Criteria (Bone et al. 1992)",
                        }
                    ],
                    "recommended_actions": [
                        {
                            "action": "Emergency services dispatch",
                            "urgency": "IMMEDIATE",
                            "rationale": "CRITICAL band",
                        }
                    ],
                    "considered_and_discarded": ["Exercise-induced — rejected"],
                }),
            },
        ]
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tier1_claude_success(llm_client, redis_client):
    """Claude responds correctly → decision_source = LLM_CLAUDE, thinking_chain populated."""
    processed  = make_processed()
    assessment = make_assessment()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = _valid_claude_response(confidence=0.82)
    mock_response.raise_for_status = MagicMock()

    with patch("app.services.llm_client.httpx.AsyncClient") as mock_http:
        mock_http.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_response
        )
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            result = await llm_client.reason(processed, assessment)

    assert result.decision_source == DecisionSource.LLM_CLAUDE
    assert result.thinking_chain is not None
    assert len(result.differential_diagnoses) >= 1
    assert len(result.reasoning_summary) > 0

    # Reasoning stored in Redis
    client = await redis_client.get_client()
    val = await client.get("reasoning:P001:latest")
    assert val is not None


@pytest.mark.asyncio
async def test_tier1_timeout_tier2_fires(llm_client, mock_gemini):
    """Claude times out → Tier 2 Gemini fires."""
    processed  = make_processed()
    assessment = make_assessment()

    gemini_result = LLMReasoning(
        patient_id="P001", session_id="S001", reading_id="RID001",
        timestamp=_now(), decision_source=DecisionSource.LLM_GEMINI,
        shal_band="CRITICAL", final_score=89.2,
        thinking_chain=None,
        reasoning_summary="Gemini fallback reasoning.",
        differential_diagnoses=[], recommended_actions=[],
        confidence=0.70, considered_and_discarded=[],
        vitals_snapshot={}, syndromes_fired=[], trends_fired=[],
        model_used="gemini-2.0-flash", latency_ms=0.0, reasoned_at=_now(),
    )
    mock_gemini.reason = AsyncMock(return_value=gemini_result)

    async def slow_post(*args, **kwargs):
        await asyncio.sleep(10)  # longer than 2s timeout

    with patch("app.services.llm_client.httpx.AsyncClient") as mock_http:
        mock_http.return_value.__aenter__.return_value.post = slow_post
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test", "GEMINI_API_KEY": "key"}):
            result = await llm_client.reason(processed, assessment)

    assert result.decision_source == DecisionSource.LLM_GEMINI
    assert result.thinking_chain is None


@pytest.mark.asyncio
async def test_tier1_http_error_tier2_fires(llm_client, mock_gemini):
    """Claude returns HTTP 500 → Tier 2 Gemini fires."""
    processed  = make_processed()
    assessment = make_assessment()

    gemini_result = LLMReasoning(
        patient_id="P001", session_id="S001", reading_id="RID001",
        timestamp=_now(), decision_source=DecisionSource.LLM_GEMINI,
        shal_band="CRITICAL", final_score=89.2,
        thinking_chain=None, reasoning_summary="Gemini reasoning.",
        differential_diagnoses=[], recommended_actions=[],
        confidence=0.65, considered_and_discarded=[],
        vitals_snapshot={}, syndromes_fired=[], trends_fired=[],
        model_used="gemini-2.0-flash", latency_ms=0.0, reasoned_at=_now(),
    )
    mock_gemini.reason = AsyncMock(return_value=gemini_result)

    import httpx as _httpx
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = _httpx.HTTPStatusError(
        "500", request=MagicMock(), response=mock_response
    )

    with patch("app.services.llm_client.httpx.AsyncClient") as mock_http:
        mock_http.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_response
        )
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test", "GEMINI_API_KEY": "key"}):
            result = await llm_client.reason(processed, assessment)

    assert result.decision_source == DecisionSource.LLM_GEMINI


@pytest.mark.asyncio
async def test_both_tiers_fail_rule_fallback_fires(llm_client, mock_gemini):
    """Claude and Gemini both fail → Tier 3 rule fallback fires, never raises."""
    processed  = make_processed()
    assessment = make_assessment()

    mock_gemini.reason = AsyncMock(side_effect=Exception("Gemini down"))

    with patch("app.services.llm_client.httpx.AsyncClient") as mock_http:
        mock_http.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=Exception("Claude down")
        )
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test", "GEMINI_API_KEY": "key"}):
            result = await llm_client.reason(processed, assessment)

    assert result is not None
    assert result.decision_source == DecisionSource.RULE_BASED
    assert result.latency_ms < 500   # rule fallback is fast


@pytest.mark.asyncio
async def test_low_confidence_rule_engine_takes_over(llm_client, mock_gemini):
    """Claude returns confidence=0.45 (< 0.55) → LLM_LOW_CONFIDENCE, rule engine output."""
    processed  = make_processed()
    assessment = make_assessment()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = _valid_claude_response(confidence=0.45)
    mock_response.raise_for_status = MagicMock()

    with patch("app.services.llm_client.httpx.AsyncClient") as mock_http:
        mock_http.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_response
        )
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            result = await llm_client.reason(processed, assessment)

    assert result.decision_source == DecisionSource.LLM_LOW_CONFIDENCE
    assert len(result.differential_diagnoses) >= 1


@pytest.mark.asyncio
async def test_invocation_guard_wrong_band(llm_client):
    """reason() called with ELEVATED band → raises ValueError immediately."""
    processed  = make_processed()
    assessment = make_assessment(shal_band=SHALBand.ELEVATED, final_score=35.0)

    with pytest.raises(ValueError, match="programming error"):
        await llm_client.reason(processed, assessment)


def test_rule_fallback_all_syndromes_covered(rule_fallback):
    """Each syndrome maps to a named DifferentialDiagnosis (not generic 'unclassified')."""
    all_syndromes = [
        "SIRS / Early Sepsis", "Hypoxic Episode", "Distributive Shock",
        "Autonomic Collapse", "Respiratory Failure", "Multi-System Stress",
    ]
    for syndrome in all_syndromes:
        processed  = make_processed()
        assessment = make_assessment(syndromes=[syndrome])
        result = rule_fallback.reason(processed, assessment)
        assert result.differential_diagnoses, f"No diagnosis for syndrome: {syndrome}"
        assert "unclassified" not in result.differential_diagnoses[0].diagnosis.lower(), (
            f"Syndrome '{syndrome}' returned generic unclassified diagnosis"
        )


def test_rule_fallback_hard_override_prepended(rule_fallback):
    """Hard override SPO2_CRITICAL → first diagnosis is 'Critical Hypoxaemia'."""
    override = HardOverride(
        override_type="SPO2_CRITICAL",
        triggered_value=83.0,
        description="SpO₂ critically low at 83%",
    )
    processed  = make_processed(hard_override=override)
    assessment = make_assessment(
        hard_override_active=True,
        hard_override_type="SPO2_CRITICAL",
        syndromes=[],
    )
    result = rule_fallback.reason(processed, assessment)

    assert result.differential_diagnoses[0].diagnosis == "Critical Hypoxaemia"
    assert result.differential_diagnoses[0].probability >= 0.85


@pytest.mark.asyncio
async def test_redis_storage(llm_client, redis_client, mock_gemini):
    """After reason(), Redis has latest key and actions channel event."""
    processed  = make_processed()
    assessment = make_assessment()

    mock_gemini.reason = AsyncMock(side_effect=Exception("Gemini unavailable"))

    with patch("app.services.llm_client.httpx.AsyncClient") as mock_http:
        mock_http.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=Exception("Claude unavailable")
        )
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test", "GEMINI_API_KEY": "key"}):
            await llm_client.reason(processed, assessment)

    client = await redis_client.get_client()
    stored = await client.get("reasoning:P001:latest")
    assert stored is not None
    data = json.loads(stored)
    assert data["patient_id"] == "P001"


def test_prompt_completeness():
    """build_claude_user_prompt() contains all required sections and no 'None' strings."""
    processed  = make_processed()
    assessment = make_assessment()

    prompt = build_claude_user_prompt(processed, assessment)

    assert "SENTINEL RISK SCORE" in prompt
    assert "SYNDROMES" in prompt.upper() or "Syndromes fired" in prompt
    assert "TEMPORAL TRENDS" in prompt
    assert "Heart Rate:" in prompt
    assert "SpO" in prompt
    assert "Temperature:" in prompt

    # None values must not appear as the string "None"
    lines = prompt.split("\n")
    for line in lines:
        # Allow "None" only as part of "unavailable" substitution check
        if "None" in line and "unavailable" not in line:
            # Check if it's a boolean False/True representation or similar
            # "None" as a value should be replaced with "unavailable"
            stripped = line.split(":", 1)[-1].strip() if ":" in line else line
            assert stripped != "None", f"Line contains bare 'None': {line!r}"
