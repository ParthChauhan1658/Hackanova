"""
Settings routes — emergency contacts (Redis-backed), test notifications, manual appointment booking.
Accessible at /api/v1/settings/*
"""
from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

_REDIS_NUMBERS_KEY = "sentinel:emergency_numbers"
_REDIS_EMAILS_KEY  = "sentinel:emergency_emails"


# ── helpers ────────────────────────────────────────────────────────────────────

async def _redis_list(redis, key: str) -> list[str]:
    client = await redis.get_client()
    items  = await client.lrange(key, 0, -1)
    return [item.decode() if isinstance(item, bytes) else item for item in items]


# ── models ─────────────────────────────────────────────────────────────────────

class ContactRequest(BaseModel):
    value: str


class TestSmsRequest(BaseModel):
    to_number: str
    message: str = "SENTINEL test alert — system is operational."


class TestEmailRequest(BaseModel):
    to_email: str
    subject: str = "SENTINEL Test Notification"
    message: str = "This is a test notification from SENTINEL. System is operational."


class BookAppointmentRequest(BaseModel):
    patient_id: str
    patient_name: str
    patient_email: str
    reason: str
    notes: str = ""
    minutes_from_now: int = 60
    event_type_id: Optional[int] = None  # if provided, overrides CAL_COM_EVENT_TYPE_ID env var


# ── contacts ───────────────────────────────────────────────────────────────────

@router.get("/contacts")
async def get_contacts(request: Request):
    """Return all emergency contacts (env vars + Redis additions)."""
    redis = request.app.state.redis_client
    redis_numbers = await _redis_list(redis, _REDIS_NUMBERS_KEY)
    redis_emails  = await _redis_list(redis, _REDIS_EMAILS_KEY)

    env_numbers = [
        n.strip() for n in os.getenv("EMERGENCY_CONTACT_NUMBERS", "").split(",")
        if n.strip() and not n.strip().startswith("#")
    ]
    env_emails = [
        e.strip() for e in os.getenv("EMERGENCY_CONTACT_EMAILS", "").split(",")
        if e.strip() and not e.strip().startswith("#")
    ]

    all_numbers = list(dict.fromkeys(env_numbers + redis_numbers))
    all_emails  = list(dict.fromkeys(env_emails + redis_emails))
    return {"numbers": all_numbers, "emails": all_emails}


@router.post("/contacts/number")
async def add_number(request: Request, body: ContactRequest):
    number = body.value.strip()
    if not number:
        return {"status": "error", "detail": "number required"}
    redis  = request.app.state.redis_client
    client = await redis.get_client()
    await client.lrem(_REDIS_NUMBERS_KEY, 0, number)   # dedup
    await client.rpush(_REDIS_NUMBERS_KEY, number)
    return {"status": "added", "value": number}


@router.delete("/contacts/number")
async def remove_number(request: Request, body: ContactRequest):
    redis  = request.app.state.redis_client
    client = await redis.get_client()
    await client.lrem(_REDIS_NUMBERS_KEY, 0, body.value.strip())
    return {"status": "removed"}


@router.post("/contacts/email")
async def add_email(request: Request, body: ContactRequest):
    email  = body.value.strip()
    if not email:
        return {"status": "error", "detail": "email required"}
    redis  = request.app.state.redis_client
    client = await redis.get_client()
    await client.lrem(_REDIS_EMAILS_KEY, 0, email)
    await client.rpush(_REDIS_EMAILS_KEY, email)
    return {"status": "added", "value": email}


@router.delete("/contacts/email")
async def remove_email(request: Request, body: ContactRequest):
    redis  = request.app.state.redis_client
    client = await redis.get_client()
    await client.lrem(_REDIS_EMAILS_KEY, 0, body.value.strip())
    return {"status": "removed"}


# ── test notifications ─────────────────────────────────────────────────────────

@router.post("/test-sms")
async def test_sms(body: TestSmsRequest):
    """Send a test SMS to the given number via Twilio."""
    from app.core.constants import (
        TWILIO_ACCOUNT_SID_ENV, TWILIO_AUTH_TOKEN_ENV,
        TWILIO_FROM_NUMBER_ENV, TWILIO_API_BASE, TWILIO_MESSAGES_ENDPOINT,
    )
    sid   = os.getenv(TWILIO_ACCOUNT_SID_ENV, "")
    token = os.getenv(TWILIO_AUTH_TOKEN_ENV, "")
    from_ = os.getenv(TWILIO_FROM_NUMBER_ENV, "")

    if not all([sid, token, from_]):
        return {"status": "error", "detail": "Twilio credentials not configured in .env"}

    url = f"{TWILIO_API_BASE}/{sid}{TWILIO_MESSAGES_ENDPOINT}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                data={"To": body.to_number, "From": from_, "Body": body.message},
                auth=(sid, token),
            )
            if resp.status_code >= 400:
                logger.warning("Test SMS HTTP %s: %s", resp.status_code, resp.text)
                # Twilio returns JSON with "message" and "code" fields
                try:
                    twilio_err = resp.json()
                    detail = twilio_err.get("message", resp.text)
                    code = twilio_err.get("code", "")
                    detail_full = f"Twilio error {code}: {detail}" if code else detail
                except Exception:
                    detail_full = resp.text
                return {"status": "error", "detail": detail_full}
            return {"status": "queued", "to": body.to_number, "http": resp.status_code,
                    "note": "Message queued by Twilio. Delivery depends on trial account restrictions — recipient must be a verified number on trial accounts."}
    except Exception as exc:
        logger.warning("Test SMS failed: %s", exc)
        return {"status": "error", "detail": str(exc)}


@router.post("/test-email")
async def test_email(body: TestEmailRequest):
    """Send a test email to the given address via Resend."""
    from app.core.constants import RESEND_API_KEY_ENV, RESEND_API_URL, RESEND_FROM_EMAIL_ENV, RESEND_FROM_EMAIL_DEFAULT

    api_key   = os.getenv(RESEND_API_KEY_ENV, "")
    from_addr = os.getenv(RESEND_FROM_EMAIL_ENV, RESEND_FROM_EMAIL_DEFAULT)

    if not api_key:
        return {"status": "error", "detail": "Resend API key (RESEND_API_KEY) not configured in .env"}

    html = f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;max-width:600px;margin:40px auto;padding:20px">
<div style="background:#1a6b58;padding:20px;border-radius:8px 8px 0 0">
  <h1 style="color:white;margin:0;font-size:20px">SENTINEL Clinical Escalation System</h1>
</div>
<div style="border:1px solid #ddd;border-top:none;padding:20px;border-radius:0 0 8px 8px">
  <h2 style="color:#271a0c">{body.subject}</h2>
  <p style="color:#6b5438;line-height:1.6">{body.message}</p>
  <hr style="border:none;border-top:1px solid #e4d8c4;margin:20px 0">
  <p style="color:#9b8768;font-size:12px">
    Automated notification from SENTINEL Clinical Escalation Agent.<br>
    Do not reply to this email.
  </p>
</div>
</body></html>"""

    payload = {
        "from":    from_addr,
        "to":      [body.to_email],
        "subject": body.subject,
        "html":    html,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                RESEND_API_URL,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code >= 400:
                logger.warning("Test email (Resend) HTTP %s: %s", resp.status_code, resp.text)
                return {"status": "error", "detail": f"HTTP {resp.status_code}: {resp.text}"}
            return {"status": "sent", "to": body.to_email, "http": resp.status_code}
    except Exception as exc:
        logger.warning("Test email failed: %s", exc)
        return {"status": "error", "detail": str(exc)}


# ── manual appointment ─────────────────────────────────────────────────────────

@router.post("/book-appointment")
async def book_appointment(body: BookAppointmentRequest):
    """Book an appointment via Cal.com REST API."""
    from datetime import datetime, timedelta, timezone
    from app.core.constants import CAL_COM_API_BASE, CAL_COM_API_KEY_ENV, CAL_COM_EVENT_TYPE_ID_ENV

    api_key = os.getenv(CAL_COM_API_KEY_ENV, "")
    evt_id  = os.getenv(CAL_COM_EVENT_TYPE_ID_ENV, "")

    if not api_key:
        return {"status": "error", "detail": "Cal.com API key not configured in .env"}

    # Use event_type_id from request body if provided, else fall back to env var
    resolved_evt_id = body.event_type_id or (int(evt_id) if evt_id else None)
    if not resolved_evt_id:
        return {"status": "error", "detail": "No event_type_id provided and CAL_COM_EVENT_TYPE_ID not set in .env. Fetch /api/v1/settings/cal-event-types first."}

    slot_start = datetime.now(timezone.utc) + timedelta(minutes=body.minutes_from_now)
    notes_text = f"Reason: {body.reason}"
    if body.notes:
        notes_text += f"\n\nAdditional notes: {body.notes}"

    # Cal.com v2 API (2024-08-13): uses "attendee" + optional "bookingFieldsResponses"
    # (the old "responses" key was removed in this version)
    payload: dict = {
        "eventTypeId": resolved_evt_id,
        "start": slot_start.isoformat(),
        "attendee": {
            "name":     body.patient_name,
            "email":    body.patient_email,
            "timeZone": "Asia/Kolkata",
            "language": "en",
        },
        "metadata": {
            "sentinel_patient_id": body.patient_id,
            "booked_via":          "SENTINEL Settings Panel",
            "reason":              body.reason,
        },
    }
    if body.notes:
        payload["bookingFieldsResponses"] = {"notes": body.notes}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{CAL_COM_API_BASE}/bookings",
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "cal-api-version": "2024-08-13",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code >= 400:
                logger.warning("Cal.com booking HTTP %s: %s", resp.status_code, resp.text)
                return {"status": "error", "detail": f"HTTP {resp.status_code}: {resp.text}"}
            data = resp.json()
        booking_data = data.get("data", data)
        uid = str(booking_data.get("uid") or booking_data.get("id") or "created")
        return {
            "status":     "booked",
            "booking_id": uid,
            "start":      slot_start.isoformat(),
            "patient":    body.patient_name,
        }
    except Exception as exc:
        logger.warning("Manual appointment booking failed: %s", exc)
        return {"status": "error", "detail": str(exc)}


# ── Cal.com event types ─────────────────────────────────────────────────────────

@router.get("/cal-event-types")
async def get_cal_event_types():
    """Fetch available event types from Cal.com — used by frontend appointment picker."""
    from app.core.constants import CAL_COM_API_BASE, CAL_COM_API_KEY_ENV

    api_key = os.getenv(CAL_COM_API_KEY_ENV, "")
    if not api_key:
        return {"status": "error", "detail": "Cal.com API key not configured in .env", "event_types": []}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{CAL_COM_API_BASE}/event-types",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "cal-api-version": "2024-08-13",
                },
            )
            if resp.status_code >= 400:
                logger.warning("Cal.com event-types HTTP %s: %s", resp.status_code, resp.text)
                return {"status": "error", "detail": f"HTTP {resp.status_code}: {resp.text}", "event_types": []}
            data = resp.json()
            raw = data.get("data", [])
            # data may be a list or dict with eventTypeGroups
            event_types = []
            if isinstance(raw, list):
                event_types = raw
            elif isinstance(raw, dict):
                for grp in raw.get("eventTypeGroups", []):
                    event_types.extend(grp.get("eventTypes", []))
            simplified = [
                {"id": et.get("id"), "title": et.get("title", ""), "length": et.get("length", 30), "slug": et.get("slug", "")}
                for et in event_types if et.get("id")
            ]
            return {"status": "ok", "event_types": simplified}
    except Exception as exc:
        logger.warning("Cal.com event-types fetch failed: %s", exc)
        return {"status": "error", "detail": str(exc), "event_types": []}
