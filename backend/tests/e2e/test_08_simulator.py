"""
PART 9 — Simulator tests.
Requires CSV files in CSV_DATA_DIR (default: data/synthetic relative to backend/).
Redis keys use internal field names: heart_rate not heart_rate_bpm.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


SIM_PATIENT = "test_patient_simulator"
START_URL  = "/api/v1/simulator/start"
STOP_URL   = "/api/v1/simulator/stop"
STATUS_URL = "/api/v1/simulator/status"


def _get_csv_file() -> str | None:
    """Return first CSV filename found in the data directory, or None."""
    # Try both relative (to backend/) and absolute
    candidates = [
        Path(os.getenv("CSV_DATA_DIR", "data/synthetic")),
        Path(__file__).parent.parent.parent / "data" / "synthetic",
        Path(__file__).parent.parent.parent.parent / "data",
    ]
    for d in candidates:
        if d.exists():
            files = list(d.glob("*.csv"))
            if files:
                return files[0].name
    return None


@pytest.fixture(scope="module")
def csv_filename():
    name = _get_csv_file()
    if name is None:
        pytest.skip(
            "No CSV files found in data/synthetic — "
            "generate dataset first: python app/ml/train_isolation_forest.py"
        )
    return name


def test_simulator_start(http_client, base_url, csv_filename):
    resp = http_client.post(
        f"{base_url}{START_URL}",
        json={
            "patient_id":        SIM_PATIENT,
            "csv_file":          csv_filename,
            "interval_seconds":  0.5,
            "loop":              False,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("status") == "started", f"Expected 'started', got: {data}"
    print(f"\nSimulator started with {csv_filename}: {data}")


def test_simulator_status_running(http_client, base_url, csv_filename):
    # Start if not already running
    status_resp = http_client.get(f"{base_url}{STATUS_URL}/{SIM_PATIENT}")
    if status_resp.status_code == 404 or not status_resp.json().get("is_running"):
        http_client.post(
            f"{base_url}{START_URL}",
            json={"patient_id": SIM_PATIENT, "csv_file": csv_filename,
                  "interval_seconds": 0.5, "loop": True},
        )

    time.sleep(1)
    resp = http_client.get(f"{base_url}{STATUS_URL}/{SIM_PATIENT}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["is_running"] is True, f"Expected is_running=True, got: {data}"
    print(f"\nTicks sent: {data['ticks_sent']}, total rows: {data.get('total_rows')}")


def test_simulator_produces_redis_data(http_client, base_url, redis_client, csv_filename):
    # Ensure simulator is running
    status_resp = http_client.get(f"{base_url}{STATUS_URL}/{SIM_PATIENT}")
    if status_resp.status_code == 404 or not status_resp.json().get("is_running"):
        http_client.post(
            f"{base_url}{START_URL}",
            json={"patient_id": SIM_PATIENT, "csv_file": csv_filename,
                  "interval_seconds": 0.5, "loop": True},
        )

    time.sleep(3)  # 6 ticks at 0.5s
    window = redis_client.lrange(f"vitals:{SIM_PATIENT}:heart_rate:window", 0, -1)
    print(f"\nHR window after 3s: {window}")
    assert len(window) >= 1, "Simulator should have populated ring buffer"


def test_simulator_ticks_at_correct_rate(http_client, base_url, csv_filename):
    # Start with loop=True
    http_client.post(
        f"{base_url}{STOP_URL}",
        json={"patient_id": SIM_PATIENT},
    )
    time.sleep(0.5)
    http_client.post(
        f"{base_url}{START_URL}",
        json={"patient_id": SIM_PATIENT, "csv_file": csv_filename,
              "interval_seconds": 0.5, "loop": True},
    )

    resp0 = http_client.get(f"{base_url}{STATUS_URL}/{SIM_PATIENT}")
    ticks_t0 = resp0.json().get("ticks_sent", 0)

    time.sleep(5)

    resp1 = http_client.get(f"{base_url}{STATUS_URL}/{SIM_PATIENT}")
    ticks_t1 = resp1.json().get("ticks_sent", 0)
    actual = ticks_t1 - ticks_t0

    print(f"\nTicks in 5s: {actual} (expected ~10)")
    assert actual >= 8, f"Expected >= 8 ticks in 5s, got {actual}"
    assert actual <= 12, f"Expected <= 12 ticks in 5s, got {actual}"


def test_simulator_duplicate_start_rejected(http_client, base_url, csv_filename):
    # Ensure already running
    http_client.post(
        f"{base_url}{START_URL}",
        json={"patient_id": SIM_PATIENT, "csv_file": csv_filename,
              "interval_seconds": 0.5, "loop": True},
    )

    resp = http_client.post(
        f"{base_url}{START_URL}",
        json={"patient_id": SIM_PATIENT, "csv_file": csv_filename,
              "interval_seconds": 0.5, "loop": True},
    )
    print(f"\nDuplicate start response: {resp.status_code} — {resp.text[:100]}")
    assert resp.status_code in (400, 409, 422), (
        f"Expected 400/409/422 for duplicate start, got {resp.status_code}"
    )


def test_simulator_stop(http_client, base_url):
    resp = http_client.post(
        f"{base_url}{STOP_URL}",
        json={"patient_id": SIM_PATIENT},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("status") == "stopped", f"Expected 'stopped', got: {data}"

    time.sleep(1)
    status = http_client.get(f"{base_url}{STATUS_URL}/{SIM_PATIENT}")
    # 404 = no simulator registered = not running; 200 with is_running=False also valid
    assert status.status_code in (200, 404), f"Unexpected status: {status.status_code}"
    if status.status_code == 200:
        assert status.json().get("is_running") is False
    print("\nSimulator stopped cleanly")


def test_simulator_scenario_jump_conditional(http_client, base_url, csv_filename):
    """Skip if jump endpoint not implemented."""
    resp = http_client.post(
        f"{base_url}/api/v1/simulator/jump",
        json={"patient_id": SIM_PATIENT, "scenario": "NORMAL"},
    )
    if resp.status_code == 404:
        pytest.skip("Jump endpoint not implemented yet")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") in ("jumped", "started", "ok")
    print(f"\nScenario jump: {data}")
