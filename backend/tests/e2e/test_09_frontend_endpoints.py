"""
PART 10 — Frontend endpoint readiness tests.
Verifies every endpoint the React dashboard will call.
Audit response format: {"count": N, "entries": [...]}.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime


def test_health_response_time(http_client, base_url):
    t0 = time.monotonic()
    resp = http_client.get(f"{base_url}/health")
    latency_ms = (time.monotonic() - t0) * 1000
    assert resp.status_code == 200
    assert latency_ms < 5000, f"Health endpoint took {latency_ms:.0f}ms"
    print(f"\nHealth latency: {latency_ms:.0f}ms")


def test_audit_list_endpoint(http_client, base_url):
    resp = http_client.get(f"{base_url}/api/v1/audit", params={"limit": 50})
    assert resp.status_code == 200
    data = resp.json()
    # Returns {"count": N, "entries": [...]}
    assert "entries" in data, f"Expected 'entries' key, got: {list(data.keys())}"
    entries = data["entries"]
    assert isinstance(entries, list)
    print(f"\nAudit entries available: {len(entries)}")


def test_audit_with_limit_parameter(http_client, base_url):
    resp = http_client.get(f"{base_url}/api/v1/audit", params={"limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    entries = data.get("entries", [])
    assert len(entries) <= 5
    print(f"\nAudit with limit=5: {len(entries)} entries returned")


def test_audit_patient_latest(http_client, base_url):
    resp = http_client.get(
        f"{base_url}/api/v1/audit/patient/test_patient_override/latest"
    )
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        data = resp.json()
        entries = data.get("entries", [])
        if entries:
            assert "shal_band" in entries[0]
            print(f"\nPatient latest — band: {entries[0]['shal_band']}")
        else:
            print("\nNo entries for patient — may need escalation tests to run first")
    else:
        print("\n404 for patient latest — no entries exist yet")


def test_simulator_status_unknown_patient(http_client, base_url):
    resp = http_client.get(f"{base_url}/api/v1/simulator/status/nonexistent_patient")
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        assert resp.json().get("is_running") is False
        print("\nSimulator status for unknown patient: is_running=False")
    else:
        print("\nSimulator status 404 for unknown patient — acceptable")


def test_fall_acknowledge_endpoint(http_client, base_url):
    resp = http_client.post(
        f"{base_url}/api/v1/fall/test_patient_fall/acknowledge"
    )
    # 404 = no active fall in progress (acceptable); 200 = fall acknowledged
    assert resp.status_code in (200, 404), (
        f"Expected 200 or 404, got {resp.status_code}: {resp.text}"
    )
    if resp.status_code == 200:
        data = resp.json()
        assert "acknowledged" in data.get("status", "")
        print(f"\nFall acknowledge: {data}")
    else:
        print("\nFall acknowledge 404 — no active fall in progress (acceptable)")


def test_websocket_endpoint_accessible(ws_url):
    import websockets.sync.client as ws_sync

    uri = f"{ws_url}/ws/vitals/probe_test"
    with ws_sync.connect(uri, open_timeout=5) as conn:
        assert conn is not None
    print("\nWebSocket endpoint: accessible")


def test_cors_headers_present(http_client, base_url):
    resp = http_client.get(
        f"{base_url}/health",
        headers={"Origin": "http://localhost:3000"},
    )
    assert resp.status_code == 200
    headers = {k.lower(): v for k, v in resp.headers.items()}
    assert "access-control-allow-origin" in headers, (
        "CORS header missing — React dashboard won't be able to call this API"
    )
    cors_val = headers["access-control-allow-origin"]
    print(f"\nCORS header: {cors_val}")
    assert cors_val in ("*", "http://localhost:3000"), (
        f"CORS value {cors_val!r} won't allow localhost:3000"
    )


def test_all_endpoints_return_json(http_client, base_url):
    endpoints = [
        f"{base_url}/health",
        f"{base_url}/api/v1/audit",
        f"{base_url}/api/v1/simulator/status/probe",
    ]
    for url in endpoints:
        resp = http_client.get(url)
        ct = resp.headers.get("content-type", "")
        assert "application/json" in ct, (
            f"{url} returned Content-Type: {ct!r} — expected application/json"
        )
    print("\nAll endpoints return JSON: OK")
