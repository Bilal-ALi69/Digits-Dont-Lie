"""Tests for API-key authentication."""

import os

import pytest
from fastapi.testclient import TestClient

TEST_API_KEY = "test-secret-key-12345"


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    """Ensure API_KEY is set for every test in this module."""
    monkeypatch.setenv("API_KEY", TEST_API_KEY)


def _client():
    """Create a fresh TestClient (picks up the env from monkeypatch)."""
    from app.api.server import app
    return TestClient(app)


@pytest.fixture
def production_client():
    """TestClient with app.api.server reloaded under ENVIRONMENT=production, so
    require_api_key() actually enforces the key.

    _is_production is computed once at import time (see app/api/server.py), so
    a plain env-var monkeypatch does nothing once the module has already been
    imported by an earlier test file in this session — it must be reloaded for
    the new value to take effect. Reload back to development afterward so this
    doesn't leak production mode into other test modules.
    """
    import importlib
    import app.api.server as srv
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("ENVIRONMENT", "production")
        importlib.reload(srv)
        try:
            yield TestClient(srv.app)
        finally:
            importlib.reload(srv)


class TestHealthOpen:
    def test_health_no_key(self):
        """Health endpoint must be accessible without any API key."""
        client = _client()
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestMissingKey:
    def test_analyze_missing_key(self, production_client):
        resp = production_client.post("/api/analyze", json={
            "input_type": "auto",
            "value": "$100",
        })
        assert resp.status_code == 401

    def test_classify_missing_key(self, production_client):
        resp = production_client.post("/api/classify", json={"value": "12345"})
        assert resp.status_code == 401

    def test_upload_missing_key(self, production_client):
        resp = production_client.post(
            "/api/analyze/upload",
            files={"file": ("data.csv", b"a,b\n1,2", "text/csv")},
        )
        assert resp.status_code == 401


class TestWrongKey:
    def test_analyze_wrong_key(self, production_client):
        resp = production_client.post(
            "/api/analyze",
            json={"input_type": "auto", "value": "$100"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    def test_classify_wrong_key(self, production_client):
        resp = production_client.post(
            "/api/classify",
            json={"value": "12345"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    def test_upload_wrong_key(self, production_client):
        resp = production_client.post(
            "/api/analyze/upload",
            files={"file": ("data.csv", b"a,b\n1,2", "text/csv")},
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401


class TestCorrectKey:
    def test_analyze_correct_key(self, production_client):
        resp = production_client.post(
            "/api/analyze",
            json={"input_type": "manual_dataset", "values": [100, 200, 300] * 20},
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert resp.status_code == 200

    def test_classify_correct_key(self, production_client):
        resp = production_client.post(
            "/api/classify",
            json={"value": "4532015112830366"},
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert resp.status_code == 200
        assert resp.json()["recommended_type"] == "card_number"

    def test_upload_correct_key(self, production_client):
        csv_content = b"id,amount\n1,100\n2,200\n3,300\n"
        resp = production_client.post(
            "/api/analyze/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert resp.status_code == 200


class TestApiKeyStartupFailure:
    def test_missing_env_var_raises(self, monkeypatch):
        """If API_KEY is unset, the lifespan startup raises RuntimeError."""
        monkeypatch.delenv("API_KEY", raising=False)
        from app.api.server import _get_api_key
        with pytest.raises(RuntimeError, match="API_KEY"):
            _get_api_key()

    def test_startup_passes_with_key(self):
        """Startup succeeds when API_KEY is set."""
        from app.api.server import _get_api_key
        result = _get_api_key()
        assert result == TEST_API_KEY


class Test401BodyFormat:
    def test_401_is_json_not_trace(self, production_client):
        resp = production_client.post(
            "/api/analyze",
            json={"input_type": "auto", "value": "$100"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert "detail" in body
        assert isinstance(body["detail"], str)
        assert "API key" in body["detail"]


class TestDocsGating:
    def test_docs_available_in_development(self):
        """In non-production, /docs and /redoc should be accessible."""
        import importlib
        import app.api.server as srv
        # Simulate development environment
        monkeypatch_ctx = __import__("pytest").MonkeyPatch()
        monkeypatch_ctx.setenv("ENVIRONMENT", "development")
        try:
            importlib.reload(srv)
            client = TestClient(srv.app)
            resp = client.get("/docs")
            assert resp.status_code == 200
        finally:
            monkeypatch_ctx.undo()
            importlib.reload(srv)

    def test_health_always_works(self):
        """Health endpoint must always be reachable regardless of docs gating."""
        client = _client()
        resp = client.get("/api/health")
        assert resp.status_code == 200
