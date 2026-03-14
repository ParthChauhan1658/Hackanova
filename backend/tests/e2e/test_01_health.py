"""
PART 2 — Health and startup tests.
"""
from __future__ import annotations


def test_health_returns_200(http_client, base_url):
    resp = http_client.get(f"{base_url}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "redis" in data
    assert "database" in data
    print(f"\nHealth response: {data}")


def test_redis_connected(http_client, base_url):
    resp = http_client.get(f"{base_url}/health")
    data = resp.json()
    assert data["redis"] == "connected", (
        f"Redis status: {data['redis']} — is Redis running on port 6379?"
    )
    print(f"\nRedis status: {data['redis']}")


def test_database_configured(http_client, base_url):
    resp = http_client.get(f"{base_url}/health")
    data = resp.json()
    # "configured" means DATABASE_URL env var is set; "default_url" means it is not
    db_status = data.get("database", "missing")
    assert db_status in ("configured", "connected"), (
        f"Database status: {db_status}"
    )
    print(f"\nDatabase status: {db_status}")


def test_isolation_forest_status_present(http_client, base_url):
    resp = http_client.get(f"{base_url}/health")
    data = resp.json()
    assert "isolation_forest" in data
    if_status = data["isolation_forest"]
    # Do NOT fail if not_loaded — model file may not exist in all environments
    print(f"\nIF model status: {if_status}")


def test_docs_accessible(http_client, base_url):
    resp = http_client.get(f"{base_url}/docs")
    assert resp.status_code == 200
    print("\nSwagger UI: accessible")


def test_openapi_schema_accessible(http_client, base_url):
    resp = http_client.get(f"{base_url}/openapi.json")
    assert resp.status_code == 200
    data = resp.json()
    assert "paths" in data
    print(f"\nOpenAPI paths: {list(data['paths'].keys())[:5]} ...")
