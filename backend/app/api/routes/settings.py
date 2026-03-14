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
    event_type_uri: Optional[str] = None  # Calendly event type URI; falls back to CALENDLY_EVENT_TYPE_URI env var


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
    """Create a Calendly scheduling link and return the booking URL to the caller."""
    from urllib.parse import quote
    from app.core.constants import CALENDLY_API_TOKEN_ENV, CALENDLY_EVENT_TYPE_URI_ENV, CALENDLY_API_BASE

    api_token = os.getenv(CALENDLY_API_TOKEN_ENV, "")
    if not api_token:
        return {"status": "error", "detail": "Calendly API token (CALENDLY_API_TOKEN) not configured in .env"}

    event_type_uri = body.event_type_uri or os.getenv(CALENDLY_EVENT_TYPE_URI_ENV, "")
    if not event_type_uri:
        return {
            "status": "error",
            "detail": "No event_type_uri provided and CALENDLY_EVENT_TYPE_URI not set in .env. "
                      "Fetch /api/v1/settings/calendly-event-types first.",
        }

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{CALENDLY_API_BASE}/scheduling_links",
                json={
                    "max_event_count": 1,
                    "owner":      event_type_uri,
                    "owner_type": "EventType",
                },
                headers=headers,
            )
            if resp.status_code >= 400:
                logger.warning("Calendly scheduling_links HTTP %s: %s", resp.status_code, resp.text)
                return {"status": "error", "detail": f"HTTP {resp.status_code}: {resp.text}"}
            data = resp.json()

        booking_url = data["resource"]["booking_url"]
        # Pre-fill patient name and email via Calendly URL parameters
        booking_url += f"?name={quote(body.patient_name)}&email={quote(body.patient_email)}"
        if body.reason:
            booking_url += f"&a1={quote(body.reason)}"

        logger.info(
            "Calendly scheduling link created for patient %s — %s",
            body.patient_id, booking_url,
        )
        return {
            "status":      "scheduled",
            "booking_url": booking_url,
            "patient":     body.patient_name,
        }
    except Exception as exc:
        logger.warning("Calendly booking link creation failed: %s", exc)
        return {"status": "error", "detail": str(exc)}


# ── Calendly event types ────────────────────────────────────────────────────────

@router.get("/calendly-event-types")
async def get_calendly_event_types():
    """Fetch active event types from Calendly — used by frontend appointment picker."""
    from app.core.constants import CALENDLY_API_TOKEN_ENV, CALENDLY_API_BASE

    api_token = os.getenv(CALENDLY_API_TOKEN_ENV, "")
    if not api_token:
        return {"status": "error", "detail": "Calendly API token (CALENDLY_API_TOKEN) not configured in .env", "event_types": []}

    headers = {"Authorization": f"Bearer {api_token}"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Step 1: get current user URI
            me_resp = await client.get(f"{CALENDLY_API_BASE}/users/me", headers=headers)
            if me_resp.status_code >= 400:
                logger.warning("Calendly /users/me HTTP %s: %s", me_resp.status_code, me_resp.text)
                return {
                    "status": "error",
                    "detail": f"Calendly auth failed — HTTP {me_resp.status_code}. Check your CALENDLY_API_TOKEN.",
                    "event_types": [],
                }
            user_uri = me_resp.json()["resource"]["uri"]

            # Step 2: list active event types for this user
            et_resp = await client.get(
                f"{CALENDLY_API_BASE}/event_types",
                params={"user": user_uri, "active": "true"},
                headers=headers,
            )
            if et_resp.status_code >= 400:
                logger.warning("Calendly /event_types HTTP %s: %s", et_resp.status_code, et_resp.text)
                return {"status": "error", "detail": f"HTTP {et_resp.status_code}: {et_resp.text}", "event_types": []}

            items = et_resp.json().get("collection", [])
            simplified = [
                {
                    "uri":      et["uri"],
                    "name":     et.get("name", ""),
                    "duration": et.get("duration", 30),
                    "slug":     et.get("slug", ""),
                    "color":    et.get("color", ""),
                }
                for et in items
            ]
            return {"status": "ok", "event_types": simplified}
    except Exception as exc:
        logger.warning("Calendly event-types fetch failed: %s", exc)
        return {"status": "error", "detail": str(exc), "event_types": []}
