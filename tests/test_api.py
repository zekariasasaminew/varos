"""Integration tests for the VAROS REST API.

Uses FastAPI's TestClient (synchronous HTTPX wrapper) — no running server needed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from varos.api.app import app
from varos.api.database import init_db

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def setup_db(tmp_path_factory):
    """Create a fresh in-memory DB for each test module."""
    import varos.api.database as db_module
    from sqlalchemy import create_engine
    from varos.api.models import Base

    # Override with in-memory SQLite so tests don't touch varos.db
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    original = db_module.engine
    db_module.engine = engine
    # Patch SessionLocal
    from sqlalchemy.orm import sessionmaker
    db_module.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield
    db_module.engine = original


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def registered_user(client):
    """Register a test user and return (api_key, user_data)."""
    resp = client.post("/v1/register", json={
        "email": "apitest@varos.io",
        "name": "API Tester",
        "organization": "Test Lab",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return data["api_key"], data


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_register_creates_user(client):
    r = client.post("/v1/register", json={"email": "new@lab.edu", "name": "Lab User"})
    assert r.status_code == 201
    data = r.json()
    assert data["tier"] == "free"
    assert data["api_key"].startswith("vrs_")
    assert data["credits_limit"] == 10


def test_register_duplicate_email(client):
    client.post("/v1/register", json={"email": "dupe@lab.edu", "name": "First"})
    r = client.post("/v1/register", json={"email": "dupe@lab.edu", "name": "Second"})
    assert r.status_code == 409


def test_register_invalid_email(client):
    r = client.post("/v1/register", json={"email": "not-an-email", "name": "Bad"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_classify_requires_api_key(client):
    r = client.post("/v1/classify", json={"variant": "BRCA1:c.5266dup"})
    assert r.status_code == 401


def test_classify_rejects_bad_key(client):
    r = client.post(
        "/v1/classify",
        json={"variant": "BRCA1:c.5266dup"},
        headers={"X-VAROS-KEY": "vrs_invalid_key_xxxx"},
    )
    assert r.status_code == 401


def test_classify_accepts_bearer_token(client, registered_user):
    api_key, _ = registered_user
    r = client.post(
        "/v1/classify",
        json={"variant": "BRCA1:c.5266dup", "genome_build": "GRCh38"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert r.status_code == 200
    assert r.json()["classification"] is not None


# ---------------------------------------------------------------------------
# Classification endpoint
# ---------------------------------------------------------------------------

def test_classify_returns_valid_result(client, registered_user):
    api_key, _ = registered_user
    r = client.post(
        "/v1/classify",
        json={"variant": "BRCA1:c.5266dup", "genome_build": "GRCh38"},
        headers={"X-VAROS-KEY": api_key},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["classification"] in [
        "Pathogenic", "Likely Pathogenic", "VUS",
        "Likely Benign", "Benign",
    ]
    assert 0 <= body["confidence"] <= 100
    assert isinstance(body["criteria_triggered"], list)
    assert "classification" in body


def test_classify_brca1_frameshift_is_pathogenic(client, registered_user):
    """BRCA1:c.5266dup is the classic pathogenic frameshift — must be LP or P."""
    api_key, _ = registered_user
    r = client.post(
        "/v1/classify",
        json={"variant": "BRCA1:c.5266dup"},
        headers={"X-VAROS-KEY": api_key},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["classification"] in ["Pathogenic", "Likely Pathogenic"]


# ---------------------------------------------------------------------------
# /me and /usage endpoints
# ---------------------------------------------------------------------------

def test_me_endpoint(client, registered_user):
    api_key, _ = registered_user
    r = client.get("/v1/me", headers={"X-VAROS-KEY": api_key})
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "free"
    assert "credits_used" in body
    assert "credits_remaining" in body


def test_usage_endpoint(client, registered_user):
    api_key, _ = registered_user
    r = client.get("/v1/usage", headers={"X-VAROS-KEY": api_key})
    assert r.status_code == 200
    body = r.json()
    assert "credits_used" in body
    assert "credits_limit" in body


def test_usage_increments_after_classify(client, registered_user):
    api_key, _ = registered_user
    r1 = client.get("/v1/usage", headers={"X-VAROS-KEY": api_key})
    used_before = r1.json()["credits_used"]

    client.post(
        "/v1/classify",
        json={"variant": "BRCA2:p.Arg2988Cys"},
        headers={"X-VAROS-KEY": api_key},
    )

    r2 = client.get("/v1/usage", headers={"X-VAROS-KEY": api_key})
    used_after = r2.json()["credits_used"]
    assert used_after == used_before + 1


# ---------------------------------------------------------------------------
# Quota enforcement
# ---------------------------------------------------------------------------

def test_quota_exceeded_returns_429(client):
    """Register a fresh free-tier user, exhaust quota, expect 429."""
    r = client.post("/v1/register", json={"email": "quota@varos.io", "name": "Quota Tester"})
    api_key = r.json()["api_key"]

    # Burn through the 10-variant free quota
    for _ in range(10):
        resp = client.post(
            "/v1/classify",
            json={"variant": "BRCA1:c.5266dup"},
            headers={"X-VAROS-KEY": api_key},
        )
        # Each should succeed until quota is exhausted
        assert resp.status_code in (200, 429)

    # Next request must be 429
    r = client.post(
        "/v1/classify",
        json={"variant": "BRCA1:c.5266dup"},
        headers={"X-VAROS-KEY": api_key},
    )
    assert r.status_code == 429
    assert "quota" in r.json()["detail"].lower()
