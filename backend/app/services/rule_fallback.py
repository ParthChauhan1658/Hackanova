"""
RuleFallback — Tier 3 deterministic reasoning from RiskAssessment data.
Pure Python, no async, no external calls. Must complete < 5ms.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.models.assessment import RiskAssessment, SHALBand
from app.models.reasoning import (
    DecisionSource,
    DifferentialDiagnosis,
    LLMReasoning,
    RecommendedAction,
)
from app.models.vitals import ActivityLevel, ProcessedReading

logger = logging.getLogger(__name__)

# Syndrome → (diagnosis label, probability)
_SYNDROME_MAP: dict[str, tuple[str, float]] = {
    "SIRS / Early Sepsis":    ("Systemic Inflammatory Response / Early Sepsis", 0.72),
    "Hypoxic Episode":        ("Hypoxic Episode / Respiratory Compromise", 0.68),
    "Distributive Shock":     ("Distributive Shock (Septic or Anaphylactic)", 0.65),
    "Autonomic Collapse":     ("Autonomic Dysregulation / Severe Physiological Stress", 0.60),
    "Respiratory Failure":    ("Acute Respiratory Failure", 0.75),
    "Multi-System Stress":    ("Multi-System Physiological Stress", 0.55),
}

# Hard override type → (diagnosis label, probability)
_OVERRIDE_MAP: dict[str, tuple[str, float]] = {
    "ECG_LETHAL_RHYTHM":      ("Lethal Cardiac Arrhythmia (VT/VF)", 0.90),
    "ECG_ST_ELEVATION":       ("Acute ST-Elevation Myocardial Infarction", 0.87),
    "SPO2_CRITICAL":          ("Critical Hypoxaemia", 0.88),
    "HR_SEVERE_TACHY":        ("Sustained Severe Tachycardia", 0.82),
    "HYPERTHERMIA_CRITICAL":  ("Critical Hyperthermia", 0.85),
    "RESP_SPO2_COMBINED":     ("Combined Respiratory and Hypoxic Failure", 0.86),
    "FALL_UNRESPONSIVE":      ("Unresponsive Fall — Potential Loss of Consciousness", 0.80),
}


class RuleFallback:
    """
    Tier 3 deterministic fallback reasoning.
    Derives clinical differential from scoring engine results with no LLM calls.
    """

    def reason(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
    ) -> LLMReasoning:
        """
        Build a LLMReasoning purely from RiskAssessment and ProcessedReading.
        Never raises — wraps everything in a try/except.
        """
        try:
            return self._build_reasoning(processed, assessment)
        except Exception as exc:
            logger.error("RuleFallback.reason() internal error: %s", exc)
            return self._minimal_safe_reasoning(processed, assessment)

    def _build_reasoning(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
    ) -> LLMReasoning:
        now = datetime.now(timezone.utc)
        validated = processed.validated_vitals
        orig = processed.original

        hr    = validated.get("heart_rate")
        temp  = validated.get("body_temperature")
        rr    = validated.get("respiratory_rate")
        spo2  = validated.get("spo2")
        hrv   = validated.get("hrv_ms")
        steps = validated.get("steps_per_hour")

        diagnoses: list[DifferentialDiagnosis] = []

        # Hard override diagnosis prepended first
        if assessment.hard_override_active and assessment.hard_override_type:
            otype = assessment.hard_override_type
            label, prob = _OVERRIDE_MAP.get(otype, (f"Critical Condition: {otype}", 0.80))
            ho = processed.hard_override
            diagnoses.append(DifferentialDiagnosis(
                diagnosis=label,
                probability=prob,
                supporting_evidence=[
                    f"Hard override triggered: {otype}",
                    f"Triggered value: {ho.triggered_value if ho else 'see description'}",
                    ho.description if ho else "",
                ],
                against_evidence=[],
                clinical_source="SENTINEL Hard Override Protocol",
            ))

        # Syndrome-derived diagnoses
        for syndrome in assessment.sl3.syndromes_fired:
            if syndrome not in _SYNDROME_MAP:
                continue
            label, prob = _SYNDROME_MAP[syndrome]
            supporting: list[str] = []
            against: list[str] = ["No confirmed infection source from wearable data"]

            if syndrome == "SIRS / Early Sepsis":
                if hr is not None:   supporting.append(f"HR {hr:.0f} bpm > 90 threshold")
                if temp is not None: supporting.append(f"Temperature {temp:.1f}°C > 38.0°C threshold")
                if rr is not None:   supporting.append(f"RR {rr:.0f}/min > 20 threshold")
                supporting.append("SIRS triad fully met (Bone et al. 1992)")
                clinical_source = "SIRS Criteria (Bone et al. 1992) + qSOFA (Singer et al. JAMA 2016)"
            elif syndrome == "Hypoxic Episode":
                if spo2 is not None: supporting.append(f"SpO₂ {spo2:.1f}% < 94% threshold")
                if hr is not None:   supporting.append(f"Compensatory tachycardia HR {hr:.0f} bpm")
                supporting.append("Motion absent — rules out exercise hypoxia")
                clinical_source = "WHO Respiratory Failure + NEWS2 dual red flag"
            elif syndrome == "Distributive Shock":
                if hr is not None:  supporting.append(f"Compensatory tachycardia HR {hr:.0f} bpm > 100")
                if hrv is not None: supporting.append(f"Severe HRV collapse {hrv:.1f} ms < 30 (circulatory proxy)")
                clinical_source = "Sepsis-3 / MEWS BP + HR combination"
            elif syndrome == "Autonomic Collapse":
                if hrv is not None:    supporting.append(f"Critically suppressed HRV {hrv:.1f} ms < 25")
                if hr is not None:     supporting.append(f"Elevated HR {hr:.0f} bpm > 100")
                supporting.append("Stress score above autonomic collapse threshold")
                clinical_source = "Clinical HRV Literature, ANS Dysregulation"
            elif syndrome == "Respiratory Failure":
                if spo2 is not None: supporting.append(f"Critical SpO₂ {spo2:.1f}% ≤ 91%")
                if rr is not None:   supporting.append(f"Extreme RR {rr:.0f}/min")
                clinical_source = "NEWS2 dual red flag"
            else:  # Multi-System Stress
                supporting.append(f"Multiple Tier-A vitals simultaneously abnormal")
                supporting.extend(assessment.sl4.trends_fired)
                clinical_source = "SENTINEL Multi-System Pattern Detection"

            diagnoses.append(DifferentialDiagnosis(
                diagnosis=label,
                probability=prob,
                supporting_evidence=supporting,
                against_evidence=against,
                clinical_source=clinical_source,
            ))

        # Generic diagnosis if nothing fired and band is HIGH/CRITICAL
        if not diagnoses:
            diagnoses.append(DifferentialDiagnosis(
                diagnosis="Unclassified High-Risk Vital Pattern — manual clinical review required",
                probability=0.50,
                supporting_evidence=[
                    f"SENTINEL score {assessment.final_score}/100",
                    f"Band: {assessment.shal_band.value}",
                ],
                against_evidence=[],
                clinical_source="SENTINEL Risk Score",
            ))

        # Recommended actions
        actions: list[RecommendedAction] = []
        score = assessment.final_score
        if assessment.shal_band == SHALBand.CRITICAL:
            actions = [
                RecommendedAction(
                    action="Emergency services dispatch",
                    urgency="IMMEDIATE",
                    rationale=f"SENTINEL score {score}/100 — CRITICAL band reached",
                ),
                RecommendedAction(
                    action="Notify all emergency contacts",
                    urgency="IMMEDIATE",
                    rationale="Multiple high-risk indicators simultaneously active",
                ),
                RecommendedAction(
                    action="Prepare hospital pre-arrival notification",
                    urgency="IMMEDIATE",
                    rationale="Clinical pattern consistent with acute emergency",
                ),
            ]
        else:  # HIGH
            actions = [
                RecommendedAction(
                    action="Contact emergency contacts immediately",
                    urgency="URGENT",
                    rationale=f"SENTINEL score {score}/100 — HIGH band",
                ),
                RecommendedAction(
                    action="Schedule urgent physician appointment within 2 hours",
                    urgency="URGENT",
                    rationale="Pattern requires clinical evaluation",
                ),
            ]

        # Considered and discarded
        activity = orig.activity_context
        sig_quality = processed.signal_quality or 0.0
        is_vigorous = activity == ActivityLevel.VIGOROUS

        considered_discarded: list[str] = []
        if not is_vigorous:
            steps_val = steps if steps is not None else 0
            considered_discarded.append(
                f"Exercise-induced response — rejected: activity_level is "
                f"{activity.value if activity else 'unavailable'}, steps {steps_val:.0f}/hr"
            )
        considered_discarded.append(
            f"Wearable artefact — rejected: signal quality {sig_quality:.0f}%, "
            "pattern sustained across multiple ticks"
        )
        considered_discarded.append(
            "Panic/anxiety response — rejected: temperature elevation inconsistent "
            "with acute anxiety"
        )

        # Confidence based on syndrome count / override
        n_syndromes = len(assessment.sl3.syndromes_fired)
        if assessment.hard_override_active:
            confidence = 0.65 if n_syndromes == 0 else (0.78 if n_syndromes < 2 else 0.88)
        elif n_syndromes == 0:
            confidence = 0.52
        elif n_syndromes == 1:
            confidence = 0.65
        elif n_syndromes == 2:
            confidence = 0.78
        else:
            confidence = 0.88

        # Reasoning summary
        top_label = (
            diagnoses[0].diagnosis if diagnoses
            else assessment.hard_override_type or "Unknown"
        )
        syndromes_str = (
            ", ".join(assessment.sl3.syndromes_fired) if assessment.sl3.syndromes_fired else "none"
        )
        trends_str = (
            ", ".join(assessment.sl4.trends_fired) if assessment.sl4.trends_fired else "none"
        )
        summary = (
            f"SENTINEL rule engine: {top_label} detected. "
            f"Score {score}/100 ({assessment.shal_band.value}). "
            f"{n_syndromes} syndrome(s) fired: {syndromes_str}. "
            f"{len(assessment.sl4.trends_fired)} trend(s) confirmed: {trends_str}. "
            f"Confidence: {confidence:.0%}. "
            f"Automated escalation initiated per SHAL protocol."
        )

        return LLMReasoning(
            patient_id=orig.patient_id,
            session_id=orig.session_id,
            reading_id=orig.reading_id,
            timestamp=orig.timestamp,
            decision_source=DecisionSource.RULE_BASED,
            shal_band=assessment.shal_band.value,
            final_score=assessment.final_score,
            thinking_chain=None,
            reasoning_summary=summary,
            differential_diagnoses=diagnoses,
            recommended_actions=actions,
            confidence=confidence,
            considered_and_discarded=considered_discarded,
            vitals_snapshot={k: v for k, v in validated.items()},
            syndromes_fired=list(assessment.sl3.syndromes_fired),
            trends_fired=list(assessment.sl4.trends_fired),
            hard_override_type=assessment.hard_override_type,
            model_used=None,
            latency_ms=0.0,
            reasoned_at=now,
        )

    def _minimal_safe_reasoning(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
    ) -> LLMReasoning:
        """Absolute fallback — returned only if _build_reasoning itself raises."""
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
                f"SENTINEL fallback: high-risk pattern detected. "
                f"Score {assessment.final_score}/100 — manual review required."
            ),
            differential_diagnoses=[
                DifferentialDiagnosis(
                    diagnosis="High-Risk Pattern — manual clinical review required",
                    probability=0.50,
                    supporting_evidence=[f"Score {assessment.final_score}/100"],
                    against_evidence=[],
                    clinical_source="SENTINEL Rule Engine",
                )
            ],
            recommended_actions=[
                RecommendedAction(
                    action="Immediate manual clinical review",
                    urgency="IMMEDIATE",
                    rationale="Automated reasoning unavailable — safety escalation",
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
