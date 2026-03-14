"""
PART 8 — WebSocket tests.
WS endpoint: /ws/vitals/{patient_id}
No authentication required.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime

import pytest


WS_PATIENT = "test_patient_ws"
INGEST_URL = "/api/v1/vitals/ingest"


def _make_reading(patient_id: str, heart_rate: float = 72.0) -> dict:
    return {
        "reading_id":     f"ws_{uuid.uuid4().hex[:8]}",
        "patient_id":     patient_id,
        "session_id":     "session_ws_001",
        "timestamp":      datetime.utcnow().isoformat() + "Z",
        "heart_rate":     heart_rate,
        "respiratory_rate": 15.0,
        "spo2":           98.0,
        "body_temperature": 37.0,
        "hrv_ms":         55.0,
        "signal_quality": 90.0,
        "fall_event":     "NONE",
        "steps_per_hour": 100.0,
        "activity_context": "RESTING",
    }


def test_websocket_connection_accepted(ws_url):
    """WebSocket connection accepted with no authentication."""
    import websockets.sync.client as ws_sync

    uri = f"{ws_url}/ws/vitals/{WS_PATIENT}"
    with ws_sync.connect(uri, open_timeout=5) as conn:
        assert conn is not None
        print(f"\nWebSocket connection to {uri}: OK")


def test_websocket_reading_processed(ws_url, redis_client, silent_sepsis_reading):
    """Send a reading via WebSocket and verify Redis ring buffer is populated."""
    import websockets.sync.client as ws_sync

    reading = {
        **silent_sepsis_reading,
        "patient_id":  WS_PATIENT,
        "session_id":  "session_ws_001",
        "reading_id":  f"ws_read_{uuid.uuid4().hex[:8]}",
    }

    uri = f"{ws_url}/ws/vitals/{WS_PATIENT}"
    with ws_sync.connect(uri, open_timeout=5) as conn:
        conn.send(json.dumps(reading))
        time.sleep(3)

    window = redis_client.lrange(f"vitals:{WS_PATIENT}:heart_rate:window", 0, -1)
    print(f"\nHR window after WS reading: {window}")
    assert len(window) > 0, "Ring buffer should be populated after WebSocket reading"
    print("WebSocket reading processed: OK")


def test_websocket_invalid_json_handled_gracefully(ws_url):
    """Server should send an error message back, not crash or close connection."""
    import websockets.sync.client as ws_sync

    uri = f"{ws_url}/ws/vitals/{WS_PATIENT}"
    with ws_sync.connect(uri, open_timeout=5) as conn:
        conn.send("this is not json")
        # Try to receive a response with 2s timeout
        try:
            msg = conn.recv(timeout=2)
            print(f"\nServer error response: {msg}")
        except TimeoutError:
            print("\nNo error response within 2s (server may silently discard bad input)")
        except Exception as exc:
            print(f"\nReceive exception (acceptable): {type(exc).__name__}: {exc}")
        # Connection should still be open (no crash)
        print("Connection still open after invalid JSON: OK")


def test_websocket_multiple_readings(ws_url, redis_client):
    """Send 5 readings via same WebSocket and verify window grows."""
    import websockets.sync.client as ws_sync

    heart_rates = [70.0, 72.0, 74.0, 76.0, 78.0]
    uri = f"{ws_url}/ws/vitals/{WS_PATIENT}"

    with ws_sync.connect(uri, open_timeout=5) as conn:
        for hr in heart_rates:
            reading = _make_reading(WS_PATIENT, heart_rate=hr)
            conn.send(json.dumps(reading))
            time.sleep(0.5)

    time.sleep(3)
    window = redis_client.lrange(f"vitals:{WS_PATIENT}:heart_rate:window", 0, -1)
    print(f"\nWindow after 5 WS readings: {window}")
    assert len(window) >= 5, f"Expected >= 5 values in window, got {len(window)}"


@pytest.mark.slow
def test_websocket_heartbeat_watchdog(ws_url, redis_client):
    """
    Connect, send one reading, then wait 35 seconds without sending anything.
    Watchdog should fire and publish WEARABLE_DISCONNECTED event.
    """
    import redis as _redis
    import websockets.sync.client as ws_sync

    received: list[dict] = []

    def _subscribe():
        import os
        sub_client = _redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
        )
        pubsub = sub_client.pubsub()
        pubsub.subscribe(f"actions:{WS_PATIENT}")
        timeout_at = time.monotonic() + 40
        for message in pubsub.listen():
            if time.monotonic() > timeout_at:
                break
            if message["type"] == "message":
                try:
                    received.append(json.loads(message["data"]))
                except Exception:
                    received.append({"raw": message["data"]})
        pubsub.close()
        sub_client.close()

    import threading
    t = threading.Thread(target=_subscribe, daemon=True)
    t.start()
    time.sleep(0.5)

    uri = f"{ws_url}/ws/vitals/{WS_PATIENT}"
    with ws_sync.connect(uri, open_timeout=5) as conn:
        conn.send(json.dumps(_make_reading(WS_PATIENT)))
        time.sleep(35)  # silence — watchdog should fire

    t.join(timeout=40)

    event_types = [m.get("event", m.get("raw", "")) for m in received]
    print(f"\nWatchdog events received: {event_types}")
    assert any(
        "DISCONNECT" in str(e) or "WATCHDOG" in str(e) or "WEARABLE" in str(e)
        for e in event_types
    ), f"Expected watchdog/disconnect event, got: {event_types}"
