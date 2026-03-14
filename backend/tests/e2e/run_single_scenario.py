"""
SENTINEL Silent Sepsis E2E Scenario Test
Run this to verify the full pipeline works for the centrepiece demo scenario.

Usage: python tests/e2e/run_single_scenario.py
       (run from backend/ directory)
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

# Allow running from backend/ directory
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env", override=False)
except ImportError:
    pass

import httpx
import redis as _redis

BASE_URL   = "http://localhost:8000"
REDIS_URL  = os.getenv("REDIS_URL", "redis://localhost:6379/0")
PATIENT_ID = f"scenario_test_{uuid.uuid4().hex[:6]}"


def print_section(title: str) -> None:
    print(f"\n{'═' * 50}")
    print(f"  {title}")
    print(f"{'═' * 50}")


def print_result(label: str, value, ok: bool = True) -> None:
    icon = "✓" if ok else "✗"
    print(f"  {icon}  {label}: {value}")


def main() -> None:
    print("\nSENTINEL Silent Sepsis Scenario Test")
    print(f"Patient ID: {PATIENT_ID}")
    print(f"Time: {datetime.now().strftime('%H:%M:%S')}")

    # Pre-flight: check FastAPI is running by connecting to the TCP socket directly
    import socket as _socket
    _host, _port = "127.0.0.1", 8000
    try:
        s = _socket.create_connection((_host, _port), timeout=3)
        s.close()
    except OSError:
        print(f"\n  ✗  FastAPI is NOT running on port {_port}.")
        print("     Start it in a separate terminal:")
        print("       cd D:\\Hackanova\\backend")
        print("       venv\\Scripts\\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload")
        print("")
        sys.exit(1)

    r = _redis.from_url(REDIS_URL, decode_responses=True)

    # Step 1 — Health check
    print_section("Step 1 — Health Check")
    with httpx.Client() as client:
        resp = client.get(f"{BASE_URL}/health")
        health = resp.json()
        print_result("Status", health.get("status"))
        print_result("Redis", health.get("redis"))
        print_result("Database", health.get("database"))
        print_result("IF Model", health.get("isolation_forest", "unknown"))

    # Step 2 — Send silent sepsis reading
    # NOTE: Uses INTERNAL VitalReading field names (not CSV column names)
    print_section("Step 2 — Sending Silent Sepsis Reading")
    print("  Vitals: HR=108, RR=22, SpO2=93%, Temp=38.4°C, HRV=32ms")
    print("  (Standard monitor would show ALL GREEN)")

    reading = {
        "reading_id":         f"scenario_{uuid.uuid4().hex[:8]}",
        "patient_id":         PATIENT_ID,
        "session_id":         "scenario_session",
        "timestamp":          datetime.utcnow().isoformat() + "Z",
        # Internal field names:
        "heart_rate":         108.0,
        "respiratory_rate":   22.0,
        "spo2":               93.0,
        "ecg_rhythm":         "NORMAL",
        "ecg_st_deviation_mm": 0.1,
        "ecg_qtc_ms":         420.0,
        "body_temperature":   38.4,
        "sleep_efficiency":   72.0,
        "deep_sleep_pct":     18.0,
        "rem_pct":            22.0,
        "hrv_ms":             32.0,
        "stress_score":       68.0,
        "fall_event":         "NONE",
        "steps_per_hour":     0.0,
        "activity_context":   "RESTING",
        "age":                45,
        "gender":             "M",
        "weight_kg":          78.0,
        "has_chronic_condition": False,
        "latitude":           19.0760,
        "longitude":          72.8777,
        "location_stale":     False,
        "source":             "scenario_test",
        "signal_quality":     94.0,
    }

    start = time.monotonic()
    with httpx.Client() as client:
        resp = client.post(f"{BASE_URL}/api/v1/vitals/ingest", json=reading)
    latency = (time.monotonic() - start) * 1000

    print_result("Ingest status", resp.status_code, resp.status_code == 200)
    print_result("Response latency", f"{latency:.0f}ms", latency < 200)

    # Step 3 — Wait for pipeline
    print_section("Step 3 — Waiting for Pipeline (15s)")
    for i in range(15, 0, -3):
        print(f"  Waiting {i}s...", end="\r")
        time.sleep(3)
    print("  Pipeline processing complete          ")

    # Step 4 — Check Signal Processor output (internal key: heart_rate)
    print_section("Step 4 — Signal Processor")
    hr_window = r.lrange(f"vitals:{PATIENT_ID}:heart_rate:window", 0, -1)
    print_result(
        "Ring buffer populated",
        f"{len(hr_window)} values",
        len(hr_window) > 0,
    )
    if hr_window:
        print_result("HR in buffer", hr_window[0])

    # Step 5 — Check scoring
    print_section("Step 5 — Scoring Engine")
    hold_log      = r.get(f"hold:{PATIENT_ID}:latest")
    reasoning_raw = r.get(f"reasoning:{PATIENT_ID}:latest")

    if reasoning_raw:
        reasoning  = json.loads(reasoning_raw)
        score      = reasoning.get("final_score", "unknown")
        band       = reasoning.get("shal_band", "unknown")
        source     = reasoning.get("decision_source", "unknown")
        confidence = reasoning.get("confidence", "unknown")

        print_result(
            "Final score", f"{score}/100",
            float(score) >= 30 if score != "unknown" else False,
        )
        print_result("SHAL band", band)
        print_result("Decision source", source)
        print_result("Confidence", f"{confidence}")

        summary = reasoning.get("reasoning_summary", "")
        if summary:
            print(f"\n  Reasoning summary:")
            print(f"  '{summary[:150]}...'")
    elif hold_log:
        hold = json.loads(hold_log)
        print_result("HOLD log found", f"Band: {hold.get('shal_band')}")
        print_result("Watch condition", hold.get("watch_condition", "")[:80])
    else:
        print_result(
            "No scoring output found",
            "Pipeline may still be processing",
            False,
        )

    # Step 6 — Check audit log
    print_section("Step 6 — Audit Log")
    with httpx.Client() as client:
        resp = client.get(
            f"{BASE_URL}/api/v1/audit/patient/{PATIENT_ID}/latest"
        )
        if resp.status_code == 200:
            data = resp.json()
            entries = data.get("entries", [])
            if entries:
                entry = entries[0]
                print_result("Audit entry created", "YES")
                print_result("Band in audit",     entry.get("shal_band"))
                print_result("EMS dispatched",    entry.get("ems_dispatched"))
                print_result("SMS sent",          entry.get("sms_sent"))
                print_result(
                    "Thinking chain stored",
                    "YES" if entry.get("llm_thinking_chain") else "NO",
                )
            else:
                print_result(
                    "No audit entry yet",
                    "May not have reached CRITICAL",
                    False,
                )
        else:
            print_result("Audit endpoint error", resp.status_code, False)

    # Step 7 — Summary
    print_section("Summary")

    pipeline_worked = len(hr_window) > 0 and (
        reasoning_raw is not None or hold_log is not None
    )

    if pipeline_worked:
        print("  ✓ PIPELINE WORKING END TO END")
        if reasoning_raw:
            score = json.loads(reasoning_raw).get("final_score", 0)
            if float(score) >= 60:
                print(f"  ✓ SILENT SEPSIS DETECTED (score {score})")
            else:
                print(f"  ⚠ Score {score} — lower than expected")
                print("    Check IF model and syndrome thresholds")
    else:
        print("  ✗ PIPELINE ISSUE DETECTED")
        print("    Check FastAPI logs for errors")

    # Cleanup
    keys = r.keys(f"*{PATIENT_ID}*")
    if keys:
        r.delete(*keys)
    print(f"\n  Cleaned up {len(keys)} Redis keys")
    print("")


if __name__ == "__main__":
    main()
