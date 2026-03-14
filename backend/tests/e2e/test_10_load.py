"""
PART 11 — Load tests.
Marked @pytest.mark.slow — excluded from default run.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime

import pytest


pytestmark = pytest.mark.slow

INGEST_URL = "/api/v1/vitals/ingest"


def _make_reading(patient_id: str, heart_rate: float, session_id: str = "load_session") -> dict:
    return {
        "reading_id":     f"load_{uuid.uuid4().hex[:8]}",
        "patient_id":     patient_id,
        "session_id":     session_id,
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


def test_sustained_tick_rate_50_readings(http_client, base_url, redis_client):
    """50 readings at 500ms intervals — mean latency < 150ms, max < 500ms."""
    patient_id = "test_patient_load"
    latencies: list[float] = []
    errors = 0

    hr_values = [68.0 + (i % 11) for i in range(50)]  # cycle 68-78

    for i, hr in enumerate(hr_values):
        reading = _make_reading(patient_id, heart_rate=hr)
        t0 = time.monotonic()
        resp = http_client.post(f"{base_url}{INGEST_URL}", json=reading)
        latency_ms = (time.monotonic() - t0) * 1000
        latencies.append(latency_ms)
        if resp.status_code != 200:
            errors += 1
        time.sleep(0.5)

    time.sleep(3)

    window = redis_client.lrange(f"vitals:{patient_id}:heart_rate:window", 0, -1)
    mean_lat = sum(latencies) / len(latencies)
    max_lat  = max(latencies)
    min_lat  = min(latencies)

    print(f"\nLoad test results (50 readings at 500ms interval):")
    print(f"  Mean response latency: {mean_lat:.1f}ms")
    print(f"  Max response latency:  {max_lat:.1f}ms")
    print(f"  Min response latency:  {min_lat:.1f}ms")
    print(f"  Errors:                {errors}")
    print(f"  Ring buffer size:      {len(window)}/12")

    assert mean_lat < 150, f"Mean latency {mean_lat:.1f}ms exceeds 150ms"
    assert max_lat < 500,  f"Max latency {max_lat:.1f}ms exceeds 500ms"
    assert errors == 0,    f"{errors} errors during load test"
    assert len(window) == 12, f"Ring buffer should be 12, got {len(window)}"


def test_ring_buffer_caps_at_12(http_client, base_url, redis_client):
    """After 20 readings, ring buffer must be exactly 12 elements."""
    patient_id = "test_patient_load"

    for i in range(20):
        reading = _make_reading(patient_id, heart_rate=70.0 + i)
        http_client.post(f"{base_url}{INGEST_URL}", json=reading)

    time.sleep(3)
    window = redis_client.lrange(f"vitals:{patient_id}:heart_rate:window", 0, -1)
    print(f"\nRing buffer after 20 readings: {len(window)} elements")
    assert len(window) == 12, (
        f"Ring buffer should be capped at 12, got {len(window)}"
    )


@pytest.mark.asyncio
async def test_concurrent_patients(base_url, redis_client):
    """3 patients processing 10 readings each simultaneously."""
    import httpx

    patients = [
        "concurrent_patient_1",
        "concurrent_patient_2",
        "concurrent_patient_3",
    ]

    async def send_readings(patient_id: str):
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i in range(10):
                reading = _make_reading(patient_id, heart_rate=70.0 + i)
                await client.post(f"{base_url}{INGEST_URL}", json=reading)
                await asyncio.sleep(0.5)

    await asyncio.gather(*[send_readings(p) for p in patients])
    await asyncio.sleep(3)

    for patient_id in patients:
        window = redis_client.lrange(f"vitals:{patient_id}:heart_rate:window", 0, -1)
        assert len(window) >= 1, (
            f"Patient {patient_id} should have data in ring buffer"
        )
        print(f"\n{patient_id}: {len(window)} values in window")

    print("\nConcurrent patient test: all 3 patients processed")
