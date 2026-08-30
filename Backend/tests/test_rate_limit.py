"""Rate limiting, and the fail-closed environment default."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# The limiter itself
# ---------------------------------------------------------------------------

class TestSlidingWindow:
    def _limiter(self, limit: int, window: float = 60.0):
        from app.api.rate_limit import SlidingWindowLimiter

        return SlidingWindowLimiter(limit=limit, window_seconds=window)

    def test_requests_under_the_limit_are_allowed(self):
        limiter = self._limiter(limit=3)
        assert [limiter.check("a") for _ in range(3)] == [None, None, None]

    def test_the_request_past_the_limit_is_refused(self):
        limiter = self._limiter(limit=3)
        for _ in range(3):
            limiter.check("a")

        retry_after = limiter.check("a")
        assert retry_after is not None
        assert retry_after > 0

    def test_clients_are_counted_separately(self):
        """One caller exhausting its budget must not lock everybody else out."""
        limiter = self._limiter(limit=1)
        assert limiter.check("a") is None
        assert limiter.check("a") is not None
        assert limiter.check("b") is None

    def test_the_window_slides(self):
        limiter = self._limiter(limit=1, window=0.15)
        assert limiter.check("a") is None
        assert limiter.check("a") is not None

        import time

        time.sleep(0.2)
        assert limiter.check("a") is None, "the window never expired"

    def test_idle_clients_are_forgotten(self):
        """The limiter is a dict keyed by caller. Without eviction, a stream of
        distinct clients is itself a memory-exhaustion vector."""
        limiter = self._limiter(limit=5, window=0.05)
        for i in range(50):
            limiter.check(f"client-{i}")

        import time

        time.sleep(0.1)
        limiter.check("trigger-a-sweep")

        assert limiter.tracked_clients <= 2, f"tracked {limiter.tracked_clients}"


# ---------------------------------------------------------------------------
# Wired into the app
# ---------------------------------------------------------------------------

@pytest.fixture()
def limited_client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "3")
    monkeypatch.setenv("RATE_LIMIT_UPLOADS_PER_MINUTE", "2")
    import app.api.server as server

    importlib.reload(server)
    with TestClient(server.app) as client:
        yield client
    importlib.reload(server)


class TestRateLimitedEndpoints:
    def test_exceeding_the_limit_returns_429(self, limited_client):
        payload = {"value": "4532015112830366"}
        codes = [
            limited_client.post("/api/classify", json=payload).status_code
            for _ in range(4)
        ]

        assert codes[:3] == [200, 200, 200], codes
        assert codes[3] == 429, codes

    def test_a_refusal_says_when_to_come_back(self, limited_client):
        payload = {"value": "4532015112830366"}
        for _ in range(3):
            limited_client.post("/api/classify", json=payload)

        resp = limited_client.post("/api/classify", json=payload)
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert int(resp.headers["Retry-After"]) >= 1

    def test_health_is_not_rate_limited(self, limited_client):
        """Whether the service is up must stay answerable: the frontend polls
        this to decide between the real backend and its offline fallback."""
        codes = [limited_client.get("/api/health").status_code for _ in range(10)]
        assert set(codes) == {200}, codes

    def test_uploads_get_their_own_tighter_budget(self, limited_client):
        """OCR costs seconds of CPU per call, so it cannot share the allowance
        of endpoints that only parse a string."""
        import app.api.server as server

        assert server._upload_limiter.limit < server._general_limiter.limit


# ---------------------------------------------------------------------------
# Fail-closed configuration
# ---------------------------------------------------------------------------

class TestEnvironmentDefaultsToSecure:
    """ENVIRONMENT used to default to "development", so a deployment that simply
    forgot to set it served every endpoint unauthenticated with /docs open. The
    default is now the safe posture; development conveniences are opt-in.
    """

    def test_unset_environment_enforces_auth(self, monkeypatch):
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.setenv("API_KEY", "test-key-abcdefghijklmnop")
        import app.api.server as server

        importlib.reload(server)
        try:
            with TestClient(server.app) as client:
                resp = client.post("/api/classify", json={"value": "4532015112830366"})
            assert resp.status_code == 401
        finally:
            monkeypatch.setenv("ENVIRONMENT", "development")
            importlib.reload(server)

    def test_unset_environment_hides_the_docs(self, monkeypatch):
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.setenv("API_KEY", "test-key-abcdefghijklmnop")
        import app.api.server as server

        importlib.reload(server)
        try:
            with TestClient(server.app) as client:
                assert client.get("/docs").status_code == 404
                assert client.get("/openapi.json").status_code == 404
        finally:
            monkeypatch.setenv("ENVIRONMENT", "development")
            importlib.reload(server)

    def test_development_must_be_asked_for_explicitly(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        import app.api.server as server

        importlib.reload(server)
        with TestClient(server.app) as client:
            assert client.get("/docs").status_code == 200
