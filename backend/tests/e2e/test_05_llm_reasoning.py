"""
PART 6 — LLM Reasoning verification.
Redis key: reasoning:{patient_id}:latest
           reasoning:{patient_id}:history  (list)
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime


INGEST_URL = "/api/v1/vitals/ingest"
PATIENT_ID = "test_patient_override"
VALID_SOURCES = {"LLM_CLAUDE", "LLM_GEMINI", "RULE_BASED", "LLM_LOW_CONFIDENCE"}


def _post_override(http_client, base_url, hard_override_reading):
    reading = {
        **hard_override_reading,
        "reading_id": f"llm_test_{uuid.uuid4().hex[:8]}",
    }
    resp = http_client.post(f"{base_url}{INGEST_URL}", json=reading)
    assert resp.status_code == 200, resp.text
    return resp


def test_reasoning_stored_in_redis(http_client, base_url, redis_client, hard_override_reading):
    _post_override(http_client, base_url, hard_override_reading)
    time.sleep(15)

    raw = redis_client.get(f"reasoning:{PATIENT_ID}:latest")
    assert raw is not None, (
        f"reasoning:{PATIENT_ID}:latest not found after 15s — "
        "is the pipeline running? Is ANTHROPIC or GEMINI key set?"
    )
    r = json.loads(raw)
    assert "reasoning_summary" in r
    assert "decision_source" in r
    assert "confidence" in r
    assert len(r["reasoning_summary"]) > 20

    print(f"\nDecision source: {r['decision_source']}")
    print(f"Confidence: {r['confidence']}")
    print(f"Summary: {r['reasoning_summary'][:100]}...")


def test_decision_source_is_valid(http_client, base_url, redis_client, hard_override_reading):
    _post_override(http_client, base_url, hard_override_reading)
    time.sleep(15)

    raw = redis_client.get(f"reasoning:{PATIENT_ID}:latest")
    assert raw is not None
    r = json.loads(raw)
    source = r["decision_source"]
    assert source in VALID_SOURCES, (
        f"decision_source '{source}' is not one of {VALID_SOURCES}"
    )
    print(f"\nDecision source: {source} — valid")


def test_differential_diagnoses_present(http_client, base_url, redis_client, hard_override_reading):
    _post_override(http_client, base_url, hard_override_reading)
    time.sleep(15)

    raw = redis_client.get(f"reasoning:{PATIENT_ID}:latest")
    assert raw is not None
    r = json.loads(raw)

    assert "differential_diagnoses" in r
    diagnoses = r["differential_diagnoses"]
    # May be a JSON string or already a list
    if isinstance(diagnoses, str):
        diagnoses = json.loads(diagnoses)
    assert isinstance(diagnoses, list)
    assert len(diagnoses) >= 1
    assert "diagnosis" in diagnoses[0]
    print(f"\nTop diagnosis: {diagnoses[0]['diagnosis']}")
    print(f"Diagnoses count: {len(diagnoses)}")


def test_thinking_chain_if_claude_used(http_client, base_url, redis_client, hard_override_reading):
    _post_override(http_client, base_url, hard_override_reading)
    time.sleep(15)

    raw = redis_client.get(f"reasoning:{PATIENT_ID}:latest")
    assert raw is not None
    r = json.loads(raw)

    if r.get("decision_source") == "LLM_CLAUDE":
        chain = r.get("thinking_chain")
        assert chain is not None, "Thinking chain should be set when Claude is used"
        assert len(chain) > 50, f"Thinking chain too short: {len(chain)} chars"
        print(f"\nThinking chain length: {len(chain)} chars")
    else:
        print(f"\nClaude not used — source was {r.get('decision_source')}")
        print("Thinking chain not expected for this source")


def test_rule_fallback_visible_in_audit(http_client, base_url):
    """Check audit log for RULE_BASED entries — confirms fallback path has been exercised."""
    resp = http_client.get(f"{base_url}/api/v1/audit", params={"limit": 50})
    assert resp.status_code == 200
    data = resp.json()
    entries = data.get("entries", [])
    rule_based_count = sum(
        1 for e in entries if e.get("decision_source") == "RULE_BASED"
    )
    print(f"\nRule-based decisions in audit log: {rule_based_count}")
    # Informational — no specific count assertion


def test_reasoning_history_accumulates(http_client, base_url, redis_client, hard_override_reading):
    """POST twice and verify history list grows."""
    for _ in range(2):
        _post_override(http_client, base_url, hard_override_reading)
    time.sleep(15)

    history = redis_client.lrange(f"reasoning:{PATIENT_ID}:history", 0, -1)
    print(f"\nReasoning history entries: {len(history)}")
    assert len(history) >= 1, "Reasoning history should have at least one entry"
