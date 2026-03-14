"""
PART 3 — Single reading ingest tests.
All POST bodies use internal VitalReading field names.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime


INGEST_URL = "/api/v1/vitals/ingest"


def test_normal_reading_accepted_fast(http_client, base_url, normal_reading):
    t0 = time.monotonic()
    resp = http_client.post(f"{base_url}{INGEST_URL}", json=normal_reading)
    latency_ms = (time.monotonic() - t0) * 1000
    assert resp.status_code == 200, resp.text
    assert latency_ms < 5000, f"Response took {latency_ms:.0f}ms — expected < 5000ms"
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["patient_id"] == "test_patient_normal"
    assert "reading_id" in data
    assert "timestamp" in data
    print(f"\nNormal ingest latency: {latency_ms:.0f}ms")
    time.sleep(3)  # allow background task to complete


def test_silent_sepsis_reading_accepted(http_client, base_url, silent_sepsis_reading):
    t0 = time.monotonic()
    resp = http_client.post(f"{base_url}{INGEST_URL}", json=silent_sepsis_reading)
    latency_ms = (time.monotonic() - t0) * 1000
    assert resp.status_code == 200, resp.text
    assert latency_ms < 5000, f"Response took {latency_ms:.0f}ms"
    print(f"\nSilent sepsis ingest latency: {latency_ms:.0f}ms")
    time.sleep(3)


def test_hard_override_reading_accepted(http_client, base_url, hard_override_reading):
    resp = http_client.post(f"{base_url}{INGEST_URL}", json=hard_override_reading)
    assert resp.status_code == 200, resp.text
    print(f"\nHard override ingest: {resp.json()}")
    time.sleep(3)


def test_fall_reading_uses_fast_path(http_client, base_url, fall_reading):
    """Fall events are processed as background tasks — ingest should return quickly."""
    t0 = time.monotonic()
    resp = http_client.post(f"{base_url}{INGEST_URL}", json=fall_reading)
    latency_ms = (time.monotonic() - t0) * 1000
    assert resp.status_code == 200, resp.text
    assert latency_ms < 5000, f"Fall ingest took {latency_ms:.0f}ms — expected < 5000ms"
    print(f"\nFall reading ingest latency: {latency_ms:.0f}ms")
    time.sleep(2)


def test_low_signal_reading_accepted(http_client, base_url, low_signal_reading):
    """System should not crash on bad signal data."""
    resp = http_client.post(f"{base_url}{INGEST_URL}", json=low_signal_reading)
    assert resp.status_code == 200, resp.text
    print(f"\nLow signal ingest response: {resp.json()}")
    time.sleep(2)


def test_empty_body_returns_422(http_client, base_url):
    resp = http_client.post(f"{base_url}{INGEST_URL}", json={})
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
    print(f"\nEmpty body validation error: {resp.json()['detail'][0]['msg'] if resp.json().get('detail') else resp.text[:100]}")


def test_missing_required_fields_returns_422(http_client, base_url):
    resp = http_client.post(
        f"{base_url}{INGEST_URL}",
        json={"reading_id": "test", "patient_id": "test"},
    )
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
    print(f"\nMissing fields — 422 confirmed")


def test_duplicate_reading_id_handled(http_client, base_url, normal_reading):
    """System must handle duplicate reading_id without crashing."""
    fixed_id = f"dup_test_{uuid.uuid4().hex[:8]}"
    reading = {**normal_reading, "reading_id": fixed_id}
    resp1 = http_client.post(f"{base_url}{INGEST_URL}", json=reading)
    resp2 = http_client.post(f"{base_url}{INGEST_URL}", json=reading)
    assert resp1.status_code == 200, resp1.text
    assert resp2.status_code == 200, resp2.text
    print(f"\nDuplicate reading_id: both accepted (idempotent)")
    time.sleep(2)


def test_null_optional_fields_accepted(http_client, base_url):
    """POST reading with all optional numeric fields set to null."""
    minimal = {
        "reading_id":     f"null_test_{uuid.uuid4().hex[:8]}",
        "patient_id":     "test_patient_null",
        "session_id":     "session_null_001",
        "timestamp":      datetime.utcnow().isoformat() + "Z",
        "heart_rate":     None,
        "respiratory_rate": None,
        "spo2":           None,
        "body_temperature": None,
        "hrv_ms":         None,
        "stress_score":   None,
        "signal_quality": None,
    }
    resp = http_client.post(f"{base_url}{INGEST_URL}", json=minimal)
    assert resp.status_code == 200, resp.text
    print(f"\nNull optional fields: accepted")
    time.sleep(2)
