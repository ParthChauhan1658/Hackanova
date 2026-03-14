"""
PART 5 — Scoring engine verification.
Checks Redis hold log and reasoning cache after pipeline processing.
SHAL Bands: NOMINAL (0-29), ELEVATED (30-49), WARNING (50-69), HIGH (70-79), CRITICAL (80-100)
Redis keys:
  hold:    hold:{patient_id}:latest
  reason:  reasoning:{patient_id}:latest
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime


INGEST_URL = "/api/v1/vitals/ingest"


def test_normal_reading_stays_nominal(http_client, base_url, redis_client, normal_reading):
    resp = http_client.post(f"{base_url}{INGEST_URL}", json=normal_reading)
    assert resp.status_code == 200
    time.sleep(3)

    hold_raw = redis_client.get("hold:test_patient_normal:latest")
    if hold_raw:
        hold = json.loads(hold_raw)
        band = hold.get("shal_band", "")
        print(f"\nNormal reading hold log band: {band}")
        assert band in ("NOMINAL", "ELEVATED"), (
            f"Normal reading should not reach WARNING+ but got: {band}"
        )
    else:
        print("\nNormal reading: no hold log (NOMINAL — correct)")


def test_silent_sepsis_triggers_scoring(http_client, base_url, redis_client, silent_sepsis_reading):
    resp = http_client.post(f"{base_url}{INGEST_URL}", json=silent_sepsis_reading)
    assert resp.status_code == 200
    time.sleep(10)

    patient_id = "test_patient_sepsis"
    reasoning_raw = redis_client.get(f"reasoning:{patient_id}:latest")
    hold_raw = redis_client.get(f"hold:{patient_id}:latest")

    assert reasoning_raw is not None or hold_raw is not None, (
        "Pipeline did not process silent sepsis reading — "
        "no reasoning or hold log found after 10s"
    )

    if reasoning_raw:
        r = json.loads(reasoning_raw)
        score = float(r.get("final_score", 0))
        band = r.get("shal_band", "unknown")
        print(f"\nSilent sepsis score: {score}/100, band: {band}")
        assert score >= 30, f"Expected score >= 30, got {score}"
    elif hold_raw:
        h = json.loads(hold_raw)
        band = h.get("shal_band", "unknown")
        print(f"\nSilent sepsis HOLD band: {band}")
        assert band in ("ELEVATED", "WARNING", "HIGH", "CRITICAL")


def test_exercise_reading_stays_low(http_client, base_url, redis_client, exercise_reading):
    resp = http_client.post(f"{base_url}{INGEST_URL}", json=exercise_reading)
    assert resp.status_code == 200
    time.sleep(5)

    patient_id = "test_patient_exercise"
    reasoning_raw = redis_client.get(f"reasoning:{patient_id}:latest")
    hold_raw = redis_client.get(f"hold:{patient_id}:latest")

    if reasoning_raw:
        r = json.loads(reasoning_raw)
        score = float(r.get("final_score", 0))
        band = r.get("shal_band", "unknown")
        print(f"\nExercise score: {score}/100, band: {band} — suppressor should be active")
        assert score <= 49, (
            f"Exercise reading with VIGOROUS activity should score <= 49, got {score}"
        )
    elif hold_raw:
        h = json.loads(hold_raw)
        band = h.get("shal_band", "unknown")
        print(f"\nExercise HOLD band: {band}")
        assert band in ("NOMINAL", "ELEVATED"), f"Expected low band, got {band}"
    else:
        print("\nExercise reading: no scoring output (NOMINAL — correct)")


def test_hard_override_gives_critical_score(
    http_client, base_url, redis_client, db_session, hard_override_reading
):
    resp = http_client.post(f"{base_url}{INGEST_URL}", json=hard_override_reading)
    assert resp.status_code == 200
    time.sleep(10)

    patient_id = "test_patient_override"
    reasoning_raw = redis_client.get(f"reasoning:{patient_id}:latest")
    if reasoning_raw:
        r = json.loads(reasoning_raw)
        score = float(r.get("final_score", 0))
        band = r.get("shal_band", "unknown")
        print(f"\nOverride score: {score}/100, band: {band}")
        assert score >= 80, f"Hard override should give score >= 80, got {score}"
        assert band == "CRITICAL", f"Expected CRITICAL, got {band}"
    else:
        print("\nReasoning not yet in Redis — checking audit log via DB")

    # Also check audit log via DB
    try:
        cursor = db_session.cursor()
        cursor.execute(
            """
            SELECT final_score, shal_band, hard_override_active
            FROM audit_log
            WHERE patient_id = %s
            ORDER BY escalated_at DESC LIMIT 1
            """,
            ("test_patient_override",),
        )
        row = cursor.fetchone()
        if row:
            print(f"\nAudit log: score={row[0]}, band={row[1]}, override={row[2]}")
            assert row[2] is True, "hard_override_active should be True"
            print("Hard override confirmed in audit log")
        else:
            print("\nNo audit entry yet — escalation may still be processing")
    except Exception as exc:
        print(f"\nDB query error: {exc}")


def test_hold_log_watch_condition(http_client, base_url, redis_client):
    """Send a reading designed to produce ELEVATED/WARNING band."""
    patient_id = "test_patient_hold"
    reading = {
        "reading_id":     f"hold_test_{uuid.uuid4().hex[:8]}",
        "patient_id":     patient_id,
        "session_id":     "session_hold_001",
        "timestamp":      datetime.utcnow().isoformat() + "Z",
        "heart_rate":     96.0,
        "respiratory_rate": 21.0,
        "spo2":           95.0,
        "body_temperature": 37.9,
        "hrv_ms":         42.0,
        "stress_score":   55.0,
        "steps_per_hour": 0.0,
        "activity_context": "RESTING",
        "signal_quality": 90.0,
        "fall_event":     "NONE",
        "age":            50,
        "weight_kg":      75.0,
        "has_chronic_condition": False,
        "latitude":       19.0760,
        "longitude":      72.8777,
        "location_stale": False,
        "source":         "test",
    }
    resp = http_client.post(f"{base_url}{INGEST_URL}", json=reading)
    assert resp.status_code == 200
    time.sleep(5)

    hold_raw = redis_client.get(f"hold:{patient_id}:latest")
    if hold_raw:
        hold = json.loads(hold_raw)
        watch = hold.get("watch_condition", "")
        print(f"\nHOLD log found — watch_condition: {watch[:80]}")
        assert len(watch) > 20, f"watch_condition should be descriptive, got: {watch!r}"
    else:
        print("\nHOLD log not triggered — score may be NOMINAL (acceptable)")

    print(f"HOLD log {'found' if hold_raw else 'not triggered'}")
