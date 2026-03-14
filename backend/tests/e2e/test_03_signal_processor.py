"""
PART 4 — Signal processor Redis verification.
Redis keys use INTERNAL field names: heart_rate, spo2, etc.
Key patterns:
  window:    vitals:{patient_id}:{field}:window
  last_valid: vitals:{patient_id}:last_valid:{field}
  hrv baseline: session:{patient_id}:{session_id}:hrv_baseline
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime


INGEST_URL = "/api/v1/vitals/ingest"


def test_ring_buffer_populated_after_normal_reading(
    http_client, base_url, redis_client, normal_reading
):
    resp = http_client.post(f"{base_url}{INGEST_URL}", json=normal_reading)
    assert resp.status_code == 200
    time.sleep(2)

    # Internal field name is "heart_rate", NOT "heart_rate_bpm"
    window = redis_client.lrange(
        "vitals:test_patient_normal:heart_rate:window", 0, -1
    )
    print(f"\nHR window for test_patient_normal: {window}")
    assert len(window) > 0, "Ring buffer should have at least one value"
    # heart_rate=72 → value "72.0" in window
    assert any(abs(float(v) - 72.0) < 1.0 for v in window), (
        f"Expected ~72 in window, got: {window}"
    )


def test_last_valid_value_stored(http_client, base_url, redis_client, normal_reading):
    resp = http_client.post(f"{base_url}{INGEST_URL}", json=normal_reading)
    assert resp.status_code == 200
    time.sleep(2)

    val = redis_client.get("vitals:test_patient_normal:last_valid:heart_rate")
    print(f"\nLast valid heart_rate: {val}")
    assert val is not None, "last_valid key should be set"
    assert abs(float(val) - 72.0) < 1.0, f"Expected ~72.0, got {val}"


def test_out_of_bounds_value_discarded(http_client, base_url, redis_client, normal_reading):
    """
    heart_rate=300 is outside plausibility bounds (20-250).
    It should be discarded and last_valid should remain 72.
    """
    # First post a normal reading to set last_valid
    normal = {**normal_reading, "reading_id": f"oob_base_{uuid.uuid4().hex[:8]}"}
    http_client.post(f"{base_url}{INGEST_URL}", json=normal)
    time.sleep(1)

    # Now post a reading with OOB heart rate
    oob_reading = {
        **normal_reading,
        "reading_id": f"oob_test_{uuid.uuid4().hex[:8]}",
        "heart_rate": 300.0,  # outside [20, 250) — should be discarded
    }
    resp = http_client.post(f"{base_url}{INGEST_URL}", json=oob_reading)
    assert resp.status_code == 200
    time.sleep(2)

    val = redis_client.get("vitals:test_patient_normal:last_valid:heart_rate")
    print(f"\nLast valid after OOB reading: {val}")
    # 300 was OOB so it should NOT have updated last_valid
    if val is not None:
        assert float(val) < 250.0, (
            f"OOB value 300 should have been discarded, but last_valid={val}"
        )


def test_low_signal_does_not_push_bad_values(
    http_client, base_url, redis_client, low_signal_reading
):
    """
    signal_quality=12 is below SIGNAL_QUALITY_MINIMUM_THRESHOLD (20).
    All vitals should be flagged unreliable and NOT pushed to ring buffer.
    """
    resp = http_client.post(f"{base_url}{INGEST_URL}", json=low_signal_reading)
    assert resp.status_code == 200
    time.sleep(2)

    window = redis_client.lrange(
        "vitals:test_patient_lowsig:heart_rate:window", 0, -1
    )
    print(f"\nHR window for low_signal patient: {window}")
    # If window is empty (fresh patient) — pass
    # If window has values — none should be 249 (the bad value we sent)
    for v in window:
        assert abs(float(v) - 249.0) > 1.0, (
            f"OOB value 249 should not be in window due to low signal quality"
        )


def test_multiple_readings_build_window(http_client, base_url, redis_client):
    """POST 5 sequential readings; ring buffer should grow."""
    patient_id = "test_patient_window_build"
    session_id = "session_window_001"

    heart_rates = [70.0, 71.0, 72.0, 73.0, 74.0]
    for hr in heart_rates:
        reading = {
            "reading_id":     f"win_{uuid.uuid4().hex[:8]}",
            "patient_id":     patient_id,
            "session_id":     session_id,
            "timestamp":      datetime.utcnow().isoformat() + "Z",
            "heart_rate":     hr,
            "respiratory_rate": 15.0,
            "spo2":           98.0,
            "body_temperature": 37.0,
            "hrv_ms":         55.0,
            "signal_quality": 90.0,
            "fall_event":     "NONE",
        }
        http_client.post(f"{base_url}{INGEST_URL}", json=reading)

    time.sleep(3)

    window = redis_client.lrange(f"vitals:{patient_id}:heart_rate:window", 0, -1)
    print(f"\nWindow after 5 readings: {window}")
    assert len(window) >= 5, f"Expected >= 5 values in window, got {len(window)}"
    float_vals = [float(v) for v in window]
    assert all(69.0 <= v <= 75.0 for v in float_vals), (
        f"All values should be 70-74, got: {float_vals}"
    )

    # cleanup
    keys = redis_client.keys(f"*{patient_id}*")
    if keys:
        redis_client.delete(*keys)


def test_session_hrv_baseline_stored(http_client, base_url, redis_client, normal_reading):
    """HRV baseline key: session:{patient_id}:{session_id}:hrv_baseline"""
    resp = http_client.post(f"{base_url}{INGEST_URL}", json=normal_reading)
    assert resp.status_code == 200
    time.sleep(2)

    key = f"session:test_patient_normal:session_normal_001:hrv_baseline"
    val = redis_client.get(key)
    print(f"\nHRV baseline ({key}): {val}")
    assert val is not None, (
        f"Session HRV baseline should be set after posting reading with hrv_ms=58"
    )
    assert abs(float(val) - 58.0) < 10.0, f"Expected ~58, got {val}"
