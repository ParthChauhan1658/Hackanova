"""
NotificationService — Twilio SMS + SendGrid email + Firebase FCM push.
All calls use httpx REST directly — no SDK dependencies.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

import httpx

from app.core.constants import (
    FIREBASE_CREDENTIALS_JSON_ENV,
    FCM_DEVICE_TOKEN_KEY,
    RESEND_API_KEY_ENV,
    RESEND_API_URL,
    RESEND_FROM_EMAIL_ENV,
    RESEND_FROM_EMAIL_DEFAULT,
    TWILIO_ACCOUNT_SID_ENV,
    TWILIO_API_BASE,
    TWILIO_AUTH_TOKEN_ENV,
    TWILIO_FROM_NUMBER_ENV,
    TWILIO_MESSAGES_ENDPOINT,
)
from app.models.assessment import RiskAssessment
from app.models.escalation import ActionResult, ActionStatus
from app.models.reasoning import DecisionSource, LLMReasoning
from app.models.vitals import ProcessedReading

logger = logging.getLogger(__name__)

# Threshold flag → HTML colour
_FLAG_COLORS = {
    "CRITICAL_HIGH": "#cc0000",
    "CRITICAL_LOW":  "#cc0000",
    "WARNING_HIGH":  "#e67e00",
    "WARNING_LOW":   "#e67e00",
    "NORMAL":        "#1a7a1a",
}


class NotificationService:
    """Sends SMS, email, and FCM push notifications for SENTINEL alerts."""

    def __init__(
        self,
        twilio_account_sid: Optional[str] = None,
        twilio_auth_token: Optional[str] = None,
        twilio_from_number: Optional[str] = None,
        resend_api_key: Optional[str] = None,
        emergency_contacts: Optional[list[str]] = None,
        emergency_emails: Optional[list[str]] = None,
    ) -> None:
        self._twilio_sid    = twilio_account_sid   or os.getenv(TWILIO_ACCOUNT_SID_ENV, "")
        self._twilio_token  = twilio_auth_token    or os.getenv(TWILIO_AUTH_TOKEN_ENV, "")
        self._twilio_from   = twilio_from_number   or os.getenv(TWILIO_FROM_NUMBER_ENV, "")
        self._resend_key    = resend_api_key       or os.getenv(RESEND_API_KEY_ENV, "")
        self._resend_from   = os.getenv(RESEND_FROM_EMAIL_ENV, RESEND_FROM_EMAIL_DEFAULT)
        self._contacts      = emergency_contacts   or [
            n.strip() for n in os.getenv("EMERGENCY_CONTACT_NUMBERS", "").split(",")
            if n.strip() and not n.strip().startswith("#")
        ]
        self._emails        = emergency_emails     or [
            e.strip() for e in os.getenv("EMERGENCY_CONTACT_EMAILS", "").split(",")
            if e.strip() and not e.strip().startswith("#")
        ]

    # ── SMS ────────────────────────────────────────────────────────────────────

    async def send_critical_sms(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
        reasoning: LLMReasoning,
    ) -> ActionResult:
        """Send SMS to all emergency contacts via Twilio REST API."""
        start = time.monotonic()

        if not self._contacts:
            logger.warning("No emergency contacts configured — SMS skipped")
            return ActionResult(
                action_type="SMS", status=ActionStatus.SKIPPED,
                latency_ms=0, detail="No emergency contacts configured",
            )

        if not all([self._twilio_sid, self._twilio_token, self._twilio_from]):
            logger.warning("Twilio not configured — SMS skipped")
            return ActionResult(
                action_type="SMS", status=ActionStatus.SKIPPED,
                latency_ms=0, detail="Twilio credentials not configured",
            )

        v = processed.validated_vitals
        top_syn = (
            assessment.sl3.syndromes_fired[0]
            if assessment.sl3.syndromes_fired
            else (assessment.hard_override_type or "High-risk pattern")
        )
        pid_short = processed.original.patient_id[:12]

        def _fmt(val, suffix=""):
            return f"{val:.1f}{suffix}" if val is not None else "?"

        # Build location line if fresh GPS fix available
        loc_line = ""
        if processed.location and not processed.original.location_stale:
            lat = processed.location.latitude
            lng = processed.location.longitude
            loc_line = f"\nLoc:{lat:.5f},{lng:.5f} maps.google.com/?q={lat:.5f},{lng:.5f}"

        body = (
            f"SENTINEL {assessment.shal_band.value}\n"
            f"Pt:{pid_short} Score:{assessment.final_score:.0f}/100\n"
            f"HR:{_fmt(v.get('heart_rate'),'bpm')} "
            f"RR:{_fmt(v.get('respiratory_rate'),'/m')} "
            f"SpO2:{_fmt(v.get('spo2'))}%\n"
            f"Temp:{_fmt(v.get('body_temperature'),'C')} "
            f"HRV:{_fmt(v.get('hrv_ms'),'ms')}\n"
            f"{top_syn[:50]}"
            f"{loc_line}"
        )
        # Cap at 320 chars (2 Twilio segments)
        if len(body) > 320:
            body = body[:317] + "..."

        url = f"{TWILIO_API_BASE}/{self._twilio_sid}{TWILIO_MESSAGES_ENDPOINT}"
        errors: list[str] = []

        for contact in self._contacts:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        url,
                        data={"To": contact, "From": self._twilio_from, "Body": body},
                        auth=(self._twilio_sid, self._twilio_token),
                    )
                    resp.raise_for_status()
            except Exception as exc:
                errors.append(f"{contact}: {exc}")
                logger.warning("SMS to %s failed: %s", contact, exc)

        latency = (time.monotonic() - start) * 1000
        if errors:
            logger.info("ACTION SMS → FAILED in %.0fms", latency)
            return ActionResult(
                action_type="SMS", status=ActionStatus.FAILED,
                latency_ms=latency, detail="; ".join(errors),
            )
        logger.info("ACTION SMS → SUCCESS in %.0fms (%d recipients)", latency, len(self._contacts))
        return ActionResult(
            action_type="SMS", status=ActionStatus.SUCCESS,
            latency_ms=latency, detail=f"Sent to {len(self._contacts)} contact(s)",
        )

    # ── Voice Call ─────────────────────────────────────────────────────────────

    async def send_critical_call(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
    ) -> ActionResult:
        """Place an automated voice call to all emergency contacts via Twilio SDK."""
        start = time.monotonic()

        if not self._contacts:
            logger.warning("No emergency contacts configured — voice call skipped")
            return ActionResult(
                action_type="CALL", status=ActionStatus.SKIPPED,
                latency_ms=0, detail="No emergency contacts configured",
            )

        if not all([self._twilio_sid, self._twilio_token, self._twilio_from]):
            logger.warning("Twilio not configured — voice call skipped")
            return ActionResult(
                action_type="CALL", status=ActionStatus.SKIPPED,
                latency_ms=0, detail="Twilio credentials not configured",
            )

        pid_short = processed.original.patient_id[:12]
        top_syn = (
            assessment.sl3.syndromes_fired[0]
            if assessment.sl3.syndromes_fired
            else (assessment.hard_override_type or "critical condition")
        )
        message = (
            f"SENTINEL alert. Patient {pid_short} requires immediate attention. "
            f"Risk score {assessment.final_score:.0f} out of 100. "
            f"Condition: {top_syn[:60]}. Please respond immediately."
        )
        twiml = f'<Response><Say voice="alice">{message}</Say></Response>'

        from twilio.rest import Client as TwilioClient
        twilio_client = TwilioClient(self._twilio_sid, self._twilio_token)
        from_ = self._twilio_from

        loop = asyncio.get_event_loop()
        errors: list[str] = []

        for contact in self._contacts:
            try:
                await loop.run_in_executor(
                    None,
                    lambda to=contact: twilio_client.calls.create(
                        twiml=twiml,
                        to=to,
                        from_=from_,
                    ),
                )
            except Exception as exc:
                errors.append(f"{contact}: {exc}")
                logger.warning("Voice call to %s failed: %s", contact, exc)

        latency = (time.monotonic() - start) * 1000
        if errors:
            logger.info("ACTION CALL → FAILED in %.0fms", latency)
            return ActionResult(
                action_type="CALL", status=ActionStatus.FAILED,
                latency_ms=latency, detail="; ".join(errors),
            )
        logger.info(
            "ACTION CALL → SUCCESS in %.0fms (%d recipients)", latency, len(self._contacts)
        )
        return ActionResult(
            action_type="CALL", status=ActionStatus.SUCCESS,
            latency_ms=latency, detail=f"Called {len(self._contacts)} contact(s)",
        )

    # ── Email ──────────────────────────────────────────────────────────────────

    async def send_critical_email(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
        reasoning: LLMReasoning,
    ) -> ActionResult:
        """Send HTML email to all emergency addresses via SendGrid REST API."""
        start = time.monotonic()

        if not self._emails:
            logger.warning("No emergency emails configured — email skipped")
            return ActionResult(
                action_type="EMAIL", status=ActionStatus.SKIPPED,
                latency_ms=0, detail="No emergency emails configured",
            )

        if not self._resend_key:
            logger.warning("Resend not configured — email skipped")
            return ActionResult(
                action_type="EMAIL", status=ActionStatus.SKIPPED,
                latency_ms=0, detail="Resend API key not configured",
            )

        pid    = processed.original.patient_id
        band   = assessment.shal_band.value
        score  = assessment.final_score
        subj   = f"[SENTINEL {band}] Patient {pid} — Score {score}/100"
        html   = self._build_html_email(processed, assessment, reasoning)

        errors: list[str] = []
        for recipient in self._emails:
            payload = {
                "from":    self._resend_from,
                "to":      [recipient],
                "subject": subj,
                "html":    html,
            }
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        RESEND_API_URL,
                        json=payload,
                        headers={"Authorization": f"Bearer {self._resend_key}"},
                    )
                    if resp.status_code >= 400:
                        errors.append(f"{recipient}: HTTP {resp.status_code} {resp.text}")
                        logger.warning("Resend to %s failed: %s %s", recipient, resp.status_code, resp.text)
            except Exception as exc:
                errors.append(f"{recipient}: {exc}")
                logger.warning("Resend to %s exception: %s", recipient, exc)

        if errors:
            latency = (time.monotonic() - start) * 1000
            logger.warning("ACTION EMAIL → FAILED in %.0fms", latency)
            return ActionResult(
                action_type="EMAIL", status=ActionStatus.FAILED,
                latency_ms=latency, detail="; ".join(errors),
            )

        latency = (time.monotonic() - start) * 1000
        logger.info("ACTION EMAIL → SUCCESS in %.0fms (%d recipients)", latency, len(self._emails))
        return ActionResult(
            action_type="EMAIL", status=ActionStatus.SUCCESS,
            latency_ms=latency, detail=f"Sent to {len(self._emails)} address(es)",
        )

    def _build_html_email(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
        reasoning: LLMReasoning,
    ) -> str:
        v   = processed.validated_vitals
        tfm = processed.threshold_flags

        def fmt(val, suffix=""):
            return f"{val:.1f}{suffix}" if val is not None else "—"

        def flag_color(vital: str) -> str:
            flag = tfm.get(vital)
            return _FLAG_COLORS.get(flag.value if flag else "", "#333333")

        vitals_rows = ""
        vitals_display = [
            ("Heart Rate",       "heart_rate",       fmt(v.get("heart_rate"), " bpm")),
            ("Respiratory Rate", "respiratory_rate", fmt(v.get("respiratory_rate"), " /min")),
            ("SpO₂",             "spo2",             fmt(v.get("spo2"), "%")),
            ("Temperature",      "body_temperature", fmt(v.get("body_temperature"), "°C")),
            ("HRV (RMSSD)",      "hrv_ms",           fmt(v.get("hrv_ms"), " ms")),
            ("Stress Score",     "stress_score",     fmt(v.get("stress_score"), "/100")),
            ("Steps/Hour",       "steps_per_hour",   fmt(v.get("steps_per_hour"))),
        ]
        for label, key, value in vitals_display:
            color = flag_color(key)
            vitals_rows += (
                f"<tr><td style='padding:4px 8px'>{label}</td>"
                f"<td style='padding:4px 8px;color:{color};font-weight:bold'>{value}</td></tr>"
            )

        syndromes_html = (
            "<ul>" + "".join(f"<li>{s}</li>" for s in assessment.sl3.syndromes_fired) + "</ul>"
            if assessment.sl3.syndromes_fired else "<p>None</p>"
        )
        trends_html = (
            "<ul>" + "".join(f"<li>{t}</li>" for t in assessment.sl4.trends_fired) + "</ul>"
            if assessment.sl4.trends_fired else "<p>None</p>"
        )

        diagnoses_html = "".join(
            f"<li><b>{d.diagnosis}</b> ({d.probability*100:.0f}%) — {d.clinical_source}</li>"
            for d in reasoning.differential_diagnoses
        )

        actions_html = "".join(
            f"<li><b>[{a.urgency}]</b> {a.action} — {a.rationale}</li>"
            for a in reasoning.recommended_actions
        )

        thinking_html = ""
        if reasoning.decision_source == DecisionSource.LLM_CLAUDE and reasoning.thinking_chain:
            excerpt = reasoning.thinking_chain[:500]
            thinking_html = (
                f"<h3>Extended Thinking (Claude)</h3>"
                f"<pre style='background:#f5f5f5;padding:8px'>{excerpt}... [full chain in audit log]</pre>"
            )

        return f"""<!DOCTYPE html><html><body style='font-family:Arial,sans-serif;max-width:800px'>
<h1 style='color:#cc0000'>SENTINEL {assessment.shal_band.value} Alert</h1>
<h2>Patient {processed.original.patient_id} — Score {assessment.final_score}/100</h2>
<p>Session: {processed.original.session_id} | {processed.original.timestamp.isoformat()}</p>

<h3>Vital Signs</h3>
<table border='1' cellspacing='0' style='border-collapse:collapse'>{vitals_rows}</table>

<h3>Syndromes Fired</h3>{syndromes_html}
<h3>Trends Detected</h3>{trends_html}

<h3>Clinical Reasoning</h3>
<p><b>Source:</b> {reasoning.decision_source.value} | <b>Confidence:</b> {reasoning.confidence:.0%}</p>
<p>{reasoning.reasoning_summary}</p>
{thinking_html}

<h3>Differential Diagnoses</h3><ul>{diagnoses_html}</ul>
<h3>Recommended Actions</h3><ul>{actions_html}</ul>

<hr><p style='color:#888;font-size:12px'>SENTINEL Clinical Escalation System — not a replacement for physician judgment</p>
</body></html>"""

    # ── FCM ────────────────────────────────────────────────────────────────────

    async def send_fcm_push(
        self,
        processed: ProcessedReading,
        assessment: RiskAssessment,
    ) -> ActionResult:
        """Send FCM push notification via Firebase REST API."""
        start = time.monotonic()

        creds_json = os.getenv(FIREBASE_CREDENTIALS_JSON_ENV, "")
        if not creds_json:
            logger.warning("Firebase credentials not configured — FCM skipped")
            return ActionResult(
                action_type="FCM", status=ActionStatus.SKIPPED,
                latency_ms=0, detail="FCM not configured",
            )

        # Get FCM device token from Redis
        pid = processed.original.patient_id
        device_token = await self._get_device_token(pid)
        if not device_token:
            return ActionResult(
                action_type="FCM", status=ActionStatus.SKIPPED,
                latency_ms=0, detail=f"No FCM device token registered for patient {pid}",
            )

        try:
            access_token, project_id = await self._get_fcm_access_token(creds_json)
        except Exception as exc:
            logger.warning("FCM token acquisition failed: %s — FCM skipped", exc)
            return ActionResult(
                action_type="FCM", status=ActionStatus.SKIPPED,
                latency_ms=(time.monotonic() - start) * 1000,
                detail=f"Token acquisition failed: {exc}",
            )

        top_diag = (
            assessment.sl3.syndromes_fired[0]
            if assessment.sl3.syndromes_fired
            else "High-risk pattern"
        )
        fcm_payload = {
            "message": {
                "token": device_token,
                "notification": {
                    "title": f"SENTINEL {assessment.shal_band.value} Alert",
                    "body": f"Score {assessment.final_score}/100 — {top_diag}",
                },
                "data": {
                    "patient_id": pid,
                    "shal_band": assessment.shal_band.value,
                    "final_score": str(assessment.final_score),
                    "action": "OPEN_DASHBOARD",
                },
            }
        }

        fcm_url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    fcm_url,
                    json=fcm_payload,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                resp.raise_for_status()
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            logger.warning("ACTION FCM → FAILED in %.0fms: %s", latency, exc)
            return ActionResult(
                action_type="FCM", status=ActionStatus.FAILED,
                latency_ms=latency, detail=str(exc),
            )

        latency = (time.monotonic() - start) * 1000
        logger.info("ACTION FCM → SUCCESS in %.0fms", latency)
        return ActionResult(
            action_type="FCM", status=ActionStatus.SUCCESS,
            latency_ms=latency, detail="Push sent",
        )

    async def _get_device_token(self, patient_id: str) -> Optional[str]:
        """Look up FCM device token from Redis (best-effort, no crash)."""
        try:
            from app.core.redis_client import redis_client as _rc
            key = FCM_DEVICE_TOKEN_KEY.format(patient_id=patient_id)
            client = await _rc.get_client()
            return await client.get(key)
        except Exception:
            return None

    async def _get_fcm_access_token(self, creds_json: str) -> tuple[str, str]:
        """Obtain Firebase access token from service account credentials."""
        import asyncio
        creds = json.loads(creds_json)
        project_id = creds.get("project_id", "")

        # Use google.oauth2 (comes with firebase-admin in requirements)
        from google.oauth2 import service_account as _sa
        import google.auth.transport.requests as _req

        credentials = _sa.Credentials.from_service_account_info(
            creds,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"],
        )
        # Refresh is blocking I/O — run in thread pool
        loop = asyncio.get_event_loop()
        request = _req.Request()
        await loop.run_in_executor(None, credentials.refresh, request)
        return credentials.token, project_id
