"""Security regressions for the API surface."""

from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def prod_client(monkeypatch):
    """A client running with authentication actually enforced."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_KEY", "test-key-abcdefghijklmnop")
    import app.api.server as server

    importlib.reload(server)
    with TestClient(server.app) as client:
        yield client

    # Restore the development posture explicitly before reloading. Deleting the
    # variable and reloading would leave the module hardened for every later
    # test, because monkeypatch does not undo its own setenv until after this
    # teardown body has finished running.
    monkeypatch.setenv("ENVIRONMENT", "development")
    importlib.reload(server)


@pytest.fixture()
def client():
    """Development-mode client: auth is off, so these tests exercise the
    classification-token checks rather than the API key."""
    import app.api.server as server

    with TestClient(server.app) as c:
        yield c


class TestApiKeyTransport:
    def test_header_is_accepted(self, prod_client):
        resp = prod_client.post(
            "/api/classify",
            json={"value": "4532015112830366"},
            headers={"X-API-Key": "test-key-abcdefghijklmnop"},
        )
        assert resp.status_code == 200

    def test_missing_key_is_rejected(self, prod_client):
        resp = prod_client.post("/api/classify", json={"value": "4532015112830366"})
        assert resp.status_code == 401

    def test_key_in_query_string_is_rejected(self, prod_client):
        """A query string is recorded in access logs, browser history and the
        Referer header of any outbound request from the page. Accepting a
        credential there hands it to every one of those, so the header is the
        only transport the API honours."""
        resp = prod_client.post(
            "/api/classify?api_key=test-key-abcdefghijklmnop",
            json={"value": "4532015112830366"},
        )
        assert resp.status_code == 401


class TestConfirmedTypeValidation:
    """A classification token authorises the specific types it was issued for.

    Validation used to stop at the first confirmed field that was set, while all
    three were forwarded to the analyser — so a caller could pair a legitimate
    value type with an arbitrary document type and have the pair accepted.
    """

    def _token_for(self, client, value: str) -> tuple[str, list[str]]:
        resp = client.post("/api/classify", json={"value": value})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        types = [c["type"] for c in body["candidates"]]
        return body["classification_id"], types

    def test_a_type_the_token_never_offered_is_rejected(self, client):
        token, types = self._token_for(client, "4532015112830366")
        assert "passport" not in types

        resp = client.post(
            "/api/analyze",
            json={
                "input_type": "manual_number",
                "value": "4532015112830366",
                "classification_id": token,
                "confirmed_document_type": "passport",
            },
        )
        assert resp.status_code == 400

    def test_a_bad_document_type_cannot_ride_along_with_a_good_value_type(self, client):
        token, types = self._token_for(client, "4532015112830366")
        good = next(t for t in types if t == "card_number")

        resp = client.post(
            "/api/analyze",
            json={
                "input_type": "manual_number",
                "value": "4532015112830366",
                "classification_id": token,
                "confirmed_value_type": good,
                "confirmed_document_type": "passport",
            },
        )
        assert resp.status_code == 400, (
            "the unvalidated document type was accepted alongside a valid value type"
        )

    def test_types_the_token_did_offer_are_accepted(self, client):
        token, types = self._token_for(client, "4532015112830366")
        good = next(t for t in types if t == "card_number")

        resp = client.post(
            "/api/analyze",
            json={
                "input_type": "manual_number",
                "value": "4532015112830366",
                "classification_id": token,
                "confirmed_value_type": good,
            },
        )
        assert resp.status_code == 200, resp.text
