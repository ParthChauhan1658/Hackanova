"""
All prompt templates for the SENTINEL LLM Reasoning Engine.
No prompt strings live anywhere else in the codebase — import from here.
"""

from __future__ import annotations

from app.models.assessment import RiskAssessment
from app.models.vitals import ProcessedReading


def build_claude_system_prompt() -> str:
    """Return the SENTINEL clinical reasoning system prompt."""
    return (
        "You are SENTINEL's clinical reasoning engine — an AI assistant embedded in a\n"
        "real-time patient vital signs monitoring system. You are given a structured\n"
        "risk assessment produced by SENTINEL's rule-based scoring engine and asked to\n"
        "provide clinical reasoning, differential diagnoses, and recommended actions.\n"
        "Your role:\n\n"
        "Reason carefully about what the vital sign pattern means clinically\n"
        "Produce a ranked differential diagnosis list with supporting and against evidence\n"
        "Recommend specific actions with urgency levels\n"
        "Express genuine uncertainty where it exists — do not overstate confidence\n"
        "Always cite the clinical standard behind each diagnosis (NEWS2, qSOFA, SIRS, etc.)\n\n"
        "You are NOT replacing a physician. You are providing decision support to\n"
        "emergency responders and caregivers. Always acknowledge this limitation.\n"
        "Output format: You must return ONLY a valid JSON object. No preamble,\n"
        "no markdown, no explanation outside the JSON. The JSON must match this schema:\n"
        "{\n"
        '"reasoning_summary": "string — 2-3 sentence plain English summary",\n'
        '"confidence": float between 0.0 and 1.0,\n'
        '"differential_diagnoses": [\n'
        "{\n"
        '"diagnosis": "string",\n'
        '"probability": float,\n'
        '"supporting_evidence": ["string", ...],\n'
        '"against_evidence": ["string", ...],\n'
        '"clinical_source": "string"\n'
        "}\n"
        "],\n"
        '"recommended_actions": [\n'
        "{\n"
        '"action": "string",\n'
        '"urgency": "IMMEDIATE | URGENT | MONITOR",\n'
        '"rationale": "string"\n'
        "}\n"
        "],\n"
        '"considered_and_discarded": ["string", ...]\n'
        "}"
    )


def build_claude_user_prompt(
    processed: ProcessedReading,
    assessment: RiskAssessment,
) -> str:
    """
    Build the structured user prompt from actual reading and assessment values.
    None values render as 'unavailable' (never the string 'None').
    """

    def fmt(val, suffix: str = "", decimals: int = 1) -> str:
        if val is None:
            return "unavailable"
        if isinstance(val, float):
            return f"{val:.{decimals}f}{suffix}"
        return f"{val}{suffix}"

    v = processed.validated_vitals
    orig = processed.original

    # Threshold flags
    def tflag(vital: str) -> str:
        flag = processed.threshold_flags.get(vital)
        return flag.value if flag else "—"

    # Hard override section
    if assessment.hard_override_active and assessment.hard_override_type:
        ho = processed.hard_override
        hard_override_section = (
            f"Hard Override Type: {assessment.hard_override_type}\n"
            f"Triggered Value:    {fmt(ho.triggered_value if ho else None)}\n"
            f"Description:        {ho.description if ho else '—'}"
        )
    else:
        hard_override_section = "(no hard override)"

    # Top 5 contributors by points
    top5 = sorted(assessment.all_contributors, key=lambda c: c.points, reverse=True)[:5]
    top5_lines = "\n".join(
        f"  {i+1}. {c.source}: +{c.points:.1f} pts ({c.detail})"
        for i, c in enumerate(top5)
    )

    # Interpolated fields
    interpolated = [k for k, v_flag in processed.is_interpolated.items() if v_flag]
    interp_str = ", ".join(interpolated) if interpolated else "none"

    # Trends
    hr_trend   = fmt(processed.window_trends.get("heart_rate"), " bpm/min")
    spo2_trend = fmt(processed.window_trends.get("spo2"), " %/min")
    hrv_trend  = fmt(processed.window_trends.get("hrv_ms"), " ms/min")
    temp_trend = fmt(processed.window_trends.get("body_temperature"), " °C/min")

    # qSOFA
    qsofa_criteria = (
        ", ".join(assessment.sl3.qsofa_criteria_met)
        if assessment.sl3.qsofa_criteria_met
        else "none"
    )

    lines = [
        "PATIENT VITAL SIGNS — CURRENT READING",
        f"Heart Rate:         {fmt(v.get('heart_rate'), ' bpm')}  [{tflag('heart_rate')}]",
        f"Respiratory Rate:   {fmt(v.get('respiratory_rate'), ' /min')}  [{tflag('respiratory_rate')}]",
        f"SpO₂:               {fmt(v.get('spo2'), '%')}  [{tflag('spo2')}]",
        f"Temperature:        {fmt(v.get('body_temperature'), '°C')}  [{tflag('body_temperature')}]",
        f"HRV (RMSSD):        {fmt(v.get('hrv_ms'), ' ms')}  [{tflag('hrv_ms')}]",
        f"Stress Score:       {fmt(v.get('stress_score'))}/100",
        f"Activity Level:     {orig.activity_context.value if orig.activity_context else 'unavailable'}",
        f"Steps/Hour:         {fmt(v.get('steps_per_hour'))}",
        f"ECG Rhythm:         {orig.ecg_rhythm.value if orig.ecg_rhythm else 'unavailable'}",
        f"ECG ST Deviation:   {fmt(v.get('ecg_st_deviation_mm'), ' mm')}",
        f"Sleep Efficiency:   {fmt(v.get('sleep_efficiency'), '%')}",
        f"Deep Sleep:         {fmt(v.get('deep_sleep_pct'), '%')}",
        f"Fall Event:         {orig.fall_event.value}",
        f"Signal Quality:     {fmt(processed.signal_quality, '%')}",
        "",
        "Patient Context:",
        f"  Age:                   {fmt(orig.age)}",
        f"  Has Chronic Condition: {fmt(orig.has_chronic_condition)}",
        "",
        f"SENTINEL RISK SCORE: {assessment.final_score}/100  —  Band: {assessment.shal_band.value}",
        "",
        "SCORING BREAKDOWN",
        f"Sub-Layer 1 (Individual Vitals):  {assessment.sl1.normalised_points:.1f} pts",
        f"Sub-Layer 2 (Modifiers):          {assessment.sl2.additive_points:.1f} pts",
        f"Sub-Layer 3 (Syndromes):          {assessment.sl3.total_points:.1f} pts",
        f"Syndromes fired: {', '.join(assessment.sl3.syndromes_fired) or 'none'}",
        f"qSOFA score: {assessment.sl3.qsofa_score}/3  —  Criteria met: {qsofa_criteria}",
        f"Sub-Layer 4 (Temporal Trends):    {assessment.sl4.total_points:.1f} pts",
        f"Trends fired: {', '.join(assessment.sl4.trends_fired) or 'none'}",
        f"Sub-Layer 5 (Isolation Forest):   {assessment.sl5.points_added:.1f} pts",
        f"Anomaly score: {assessment.sl5.anomaly_score:.3f}  —  {assessment.sl5.xai_label or 'below threshold'}",
        f"Hard Override Active: {assessment.hard_override_active}",
        hard_override_section,
        f"MEWS Score: {assessment.mews.mews_score}  —  Review Flag: {assessment.mews.review_flag_added}",
        "",
        "TOP SCORING CONTRIBUTORS",
        top5_lines,
        "",
        "TEMPORAL TRENDS (30-second window)",
        f"HR trend:   {hr_trend}",
        f"SpO₂ trend: {spo2_trend}",
        f"HRV trend:  {hrv_trend}",
        f"Temp trend: {temp_trend}",
        "",
        "CLINICAL CONTEXT",
        f"HRV Acute Drop Detected: {processed.hrv_acute_drop}",
        f"Activity Suppressor Applied: {processed.apply_hr_vigorous_suppressor}",
        f"Sedentary Amplifier Applied: {processed.apply_hr_sedentary_amplifier}",
        f"Interpolated Fields: {interp_str}",
        f"Low Signal Quality: {processed.low_signal_quality}",
        "",
        "Based on the above, provide your clinical reasoning as JSON.",
        "If signal quality is low or multiple fields were interpolated,",
        "explicitly lower your confidence and note data quality limitations.",
    ]

    return "\n".join(lines)
