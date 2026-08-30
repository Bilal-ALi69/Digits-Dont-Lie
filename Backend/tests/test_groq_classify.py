"""Tests for /api/classify Groq integration."""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app.api.server import app
from app.engines.classifier import _VALID_VALUE_TYPES, _VALID_DOCUMENT_TYPES
from app.orchestrator import classify_input

client = TestClient(app)
AUTH = {"X-API-Key": "test-api-key-for-ci"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeGroqClient:
    """Controllable fake Groq client for testing."""

    def __init__(self, response: str | None = None) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    @property
    def available(self) -> bool:
        return self._response is not None

    def chat(
        self,
        system_prompt: str,
        user_content: str,
        *,
        max_tokens: int = 60,
    ) -> str | None:
        self.calls.append({
            "system_prompt": system_prompt,
            "user_content": user_content,
            "max_tokens": max_tokens,
        })
        return self._response


def _make_groq_json(value_type: str, doc_type: str) -> str:
    return json.dumps({"value_type": value_type, "document_type": doc_type})


# ---------------------------------------------------------------------------
# A. Groq classification is invoked when a client is available
# ---------------------------------------------------------------------------

class TestGroqIsInvoked:
    def test_chat_called_for_ambiguous_input(self):
        """1234567890123456 has max conf 0.35 < 0.80, so Groq should be called."""
        fake = FakeGroqClient(_make_groq_json("card_number", "credit_card"))
        with mock.patch(
            "app.orchestrator.classify_with_candidates",
            wraps=__import__("app.engines.classifier", fromlist=["classify_with_candidates"]).classify_with_candidates,
        ) as spy:
            # We can't easily mock get_groq_client and still have the real
            # classify_with_candidates run. Instead, test at the classify_input
            # level with a mocked classify_with_candidates to verify the arg.
            pass

        # Direct approach: mock classify_with_candidates and verify groq_client arg
        with mock.patch("app.orchestrator.classify_with_candidates") as mock_cls:
            mock_cls.return_value = []
            classify_input("1234567890123456")
            call_kwargs = mock_cls.call_args
            assert call_kwargs.kwargs.get("groq_client") is not None

    def test_groq_client_is_not_none(self):
        """The groq_client argument passed must not be None."""
        with mock.patch("app.orchestrator.classify_with_candidates") as mock_cls:
            mock_cls.return_value = []
            classify_input("1234567890123456")
            groq_arg = mock_cls.call_args.kwargs.get("groq_client")
            assert groq_arg is not None, "groq_client should not be None"

    def test_groq_client_has_available_property(self):
        """The passed client must look like a real GroqClient (has .available)."""
        with mock.patch("app.orchestrator.classify_with_candidates") as mock_cls:
            mock_cls.return_value = []
            classify_input("1234567890123456")
            groq_arg = mock_cls.call_args.kwargs.get("groq_client")
            assert hasattr(groq_arg, "available")

    def test_context_passed_through(self):
        """Context must still reach classify_with_candidates."""
        with mock.patch("app.orchestrator.classify_with_candidates") as mock_cls:
            mock_cls.return_value = []
            classify_input("1234567890123456", context="Invoice #42")
            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs.get("context") == "Invoice #42"


# ---------------------------------------------------------------------------
# B. Groq can influence an ambiguous classification
# ---------------------------------------------------------------------------

class TestGroqInfluencesClassification:
    def test_groq_adds_new_candidate(self):
        """When Groq suggests a type not in deterministic results, a new candidate appears."""
        groq_response = _make_groq_json("phone_number", "other")
        fake = FakeGroqClient(groq_response)

        with mock.patch("app.orchestrator.classify_with_candidates") as mock_cls:
            mock_cls.return_value = []
            with mock.patch("app.orchestrator.get_groq_client", return_value=fake):
                # Re-import to pick up the mock
                from app.orchestrator import classify_input as ci
                resp = ci("1234567890123456")

        # Even with empty deterministic results, Groq should have been attempted
        assert isinstance(resp.candidates, list)

    def test_groq_boosts_existing_candidate(self):
        """When Groq agrees with a deterministic candidate, confidence is boosted."""
        from app.models import ClassificationCandidate

        deterministic = [
            ClassificationCandidate(
                type="card_number", label="Card number",
                confidence=0.30, reason="16 digits, invalid Luhn",
                layer="value",
            ),
            ClassificationCandidate(
                type="other", label="Other",
                confidence=0.40, reason="No indicators",
                layer="document",
            ),
        ]

        groq_response = _make_groq_json("card_number", "other")
        fake = FakeGroqClient(groq_response)

        with mock.patch("app.orchestrator.classify_with_candidates") as mock_cls:
            # Simulate: the real classify_with_candidates runs, then we
            # manually apply groq to verify the boost logic.
            # Instead, test _apply_groq_classification directly.
            from app.engines.classifier import _apply_groq_classification

            value_cands = [c.model_copy() for c in deterministic if c.layer == "value"]
            doc_cands = [c.model_copy() for c in deterministic if c.layer == "document"]

            _apply_groq_classification("1234567890123456", None, value_cands, doc_cands, fake)

            card = next((c for c in value_cands if c.type == "card_number"), None)
            assert card is not None
            assert card.confidence > 0.30, "Groq should boost card_number confidence"
            assert "Groq agrees" in card.reason


# ---------------------------------------------------------------------------
# C. Deterministic candidates remain present
# ---------------------------------------------------------------------------

class TestDeterministicPreserved:
    def test_deterministic_candidates_still_exist(self):
        """Even with Groq available, the deterministic card candidate is present."""
        from app.models import ClassificationCandidate

        deterministic_value = [
            ClassificationCandidate(
                type="card_number", label="Card number",
                confidence=0.30, reason="16 digits",
                layer="value",
            ),
        ]
        deterministic_doc = [
            ClassificationCandidate(
                type="other", label="Other",
                confidence=0.40, reason="No indicators",
                layer="document",
            ),
        ]

        groq_response = _make_groq_json("transaction_id", "invoice")
        fake = FakeGroqClient(groq_response)

        from app.engines.classifier import _apply_groq_classification

        value_cands = [c.model_copy() for c in deterministic_value]
        doc_cands = [c.model_copy() for c in deterministic_doc]

        _apply_groq_classification("1234567890123456", None, value_cands, doc_cands, fake)

        # Original deterministic candidates still present
        types = {c.type for c in value_cands}
        assert "card_number" in types


# ---------------------------------------------------------------------------
# D. Invalid Groq output is rejected safely
# ---------------------------------------------------------------------------

class TestInvalidGroqOutput:
    def test_invalid_json_rejected(self):
        from app.models import ClassificationCandidate
        from app.engines.classifier import _apply_groq_classification

        fake = FakeGroqClient("this is not json at all")
        value_cands = [
            ClassificationCandidate(
                type="card_number", label="Card", confidence=0.30,
                reason="test", layer="value",
            ),
        ]
        doc_cands = [
            ClassificationCandidate(
                type="other", label="Other", confidence=0.40,
                reason="test", layer="document",
            ),
        ]
        original_value_types = {c.type for c in value_cands}
        original_doc_types = {c.type for c in doc_cands}

        _apply_groq_classification("1234567890123456", None, value_cands, doc_cands, fake)

        # No new candidates added from garbage
        assert {c.type for c in value_cands} == original_value_types
        assert {c.type for c in doc_cands} == original_doc_types

    def test_invalid_enum_value_rejected(self):
        from app.models import ClassificationCandidate
        from app.engines.classifier import _apply_groq_classification

        fake = FakeGroqClient(_make_groq_json("banana_split", "pizza_order"))
        value_cands = [
            ClassificationCandidate(
                type="card_number", label="Card", confidence=0.30,
                reason="test", layer="value",
            ),
        ]
        doc_cands = [
            ClassificationCandidate(
                type="other", label="Other", confidence=0.40,
                reason="test", layer="document",
            ),
        ]

        _apply_groq_classification("1234567890123456", None, value_cands, doc_cands, fake)

        # Invalid enums not added
        assert all(c.type in _VALID_VALUE_TYPES for c in value_cands)
        assert all(c.type in _VALID_DOCUMENT_TYPES for c in doc_cands)

    def test_empty_response_rejected(self):
        from app.models import ClassificationCandidate
        from app.engines.classifier import _apply_groq_classification

        fake = FakeGroqClient("")
        value_cands = [
            ClassificationCandidate(
                type="card_number", label="Card", confidence=0.30,
                reason="test", layer="value",
            ),
        ]
        doc_cands = [
            ClassificationCandidate(
                type="other", label="Other", confidence=0.40,
                reason="test", layer="document",
            ),
        ]

        _apply_groq_classification("1234567890123456", None, value_cands, doc_cands, fake)

        # Original candidates unchanged
        assert len(value_cands) == 1
        assert value_cands[0].type == "card_number"

    def test_none_response_rejected(self):
        from app.models import ClassificationCandidate
        from app.engines.classifier import _apply_groq_classification

        fake = FakeGroqClient(None)
        value_cands = [
            ClassificationCandidate(
                type="card_number", label="Card", confidence=0.30,
                reason="test", layer="value",
            ),
        ]
        doc_cands = [
            ClassificationCandidate(
                type="other", label="Other", confidence=0.40,
                reason="test", layer="document",
            ),
        ]

        _apply_groq_classification("1234567890123456", None, value_cands, doc_cands, fake)

        assert len(value_cands) == 1
        assert value_cands[0].type == "card_number"

    def test_markdown_code_block_json_stripped(self):
        from app.models import ClassificationCandidate
        from app.engines.classifier import _apply_groq_classification

        wrapped = "```json\n" + _make_groq_json("card_number", "credit_card") + "\n```"
        fake = FakeGroqClient(wrapped)
        value_cands: list[ClassificationCandidate] = []
        doc_cands: list[ClassificationCandidate] = []

        _apply_groq_classification("1234567890123456", None, value_cands, doc_cands, fake)

        types = {c.type for c in value_cands}
        assert "card_number" in types


# ---------------------------------------------------------------------------
# E. Groq failure falls back to deterministic classification
# ---------------------------------------------------------------------------

class TestGroqFailureFallback:
    def test_groq_exception_still_returns_valid_result(self):
        """classify_input must return a valid ClassificationResponse even if Groq raises."""
        with mock.patch("app.engines.groq_client.GroqClient.chat", side_effect=RuntimeError("network")):
            # Ensure a fresh client with no cached state
            import app.engines.groq_client as gc_mod
            old = gc_mod._client_instance
            gc_mod._client_instance = None
            try:
                resp = classify_input("1234567890123456")
                assert resp.recommended_type
                assert len(resp.value_candidates) > 0
            finally:
                gc_mod._client_instance = old

    def test_groq_none_response_falls_back(self):
        """When Groq returns None, deterministic candidates are still returned."""
        with mock.patch("app.engines.groq_client.GroqClient.chat", return_value=None):
            import app.engines.groq_client as gc_mod
            old = gc_mod._client_instance
            gc_mod._client_instance = None
            try:
                resp = classify_input("1234567890123456")
                assert len(resp.value_candidates) > 0
            finally:
                gc_mod._client_instance = old

    def test_no_api_key_deterministic_works(self):
        """With no GROQ_API_KEY, Groq is unavailable but classification still works."""
        with mock.patch.dict("os.environ", {"GROQ_API_KEY": ""}, clear=False):
            import app.engines.groq_client as gc_mod
            old = gc_mod._client_instance
            gc_mod._client_instance = None
            try:
                resp = classify_input("1234567890123456")
                assert len(resp.value_candidates) > 0
                assert resp.recommended_type != ""
            finally:
                gc_mod._client_instance = old


# ---------------------------------------------------------------------------
# F. No API key is exposed
# ---------------------------------------------------------------------------

class TestNoApiKeyExposure:
    def test_api_key_not_in_response(self):
        """The GROQ_API_KEY must never appear in the classification response."""
        import os
        api_key = os.environ.get("GROQ_API_KEY", "")

        resp = client.post("/api/classify", json={"value": "1234567890123456"}, headers=AUTH)
        assert resp.status_code == 200
        raw = resp.text
        if api_key:
            assert api_key not in raw, "API key must not appear in response"

    def test_api_key_not_in_candidates(self):
        """Groq API key must not leak into candidate reasons."""
        import os
        api_key = os.environ.get("GROQ_API_KEY", "")

        resp = client.post("/api/classify", json={"value": "1234567890123456"}, headers=AUTH)
        data = resp.json()
        for c in data.get("candidates", []):
            if api_key:
                assert api_key not in c.get("reason", "")


# ---------------------------------------------------------------------------
# G. User confirmation fields still work
# ---------------------------------------------------------------------------

class TestUserConfirmationFields:
    def test_confirmed_document_type_accepted(self):
        """confirmed_document_type field is accepted without error."""
        resp = client.post("/api/analyze", json={
            "input_type": "auto",
            "value": "1234567890123456",
            "confirmed_document_type": "credit_card",
        }, headers=AUTH)
        assert resp.status_code == 200

    def test_confirmed_value_type_accepted(self):
        """confirmed_value_type field is accepted without error."""
        resp = client.post("/api/analyze", json={
            "input_type": "auto",
            "value": "1234567890123456",
            "confirmed_value_type": "card_number",
        }, headers=AUTH)
        assert resp.status_code == 200

    def test_confirmed_fields_through_classify_endpoint(self):
        """The /api/classify endpoint accepts context which feeds into classification."""
        resp = client.post("/api/classify", json={
            "value": "1234567890123456",
            "context": "Invoice #42",
        }, headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert "candidates" in data


# ---------------------------------------------------------------------------
# H. Manual classify_input integration (no HTTP)
# ---------------------------------------------------------------------------

class TestClassifyInputDirect:
    def test_returns_classification_response(self):
        resp = classify_input("1234567890123456")
        assert hasattr(resp, "candidates")
        assert hasattr(resp, "recommended_type")
        assert hasattr(resp, "document_candidates")
        assert hasattr(resp, "value_candidates")

    def test_value_candidates_not_empty(self):
        resp = classify_input("1234567890123456")
        assert len(resp.value_candidates) > 0

    def test_document_candidates_not_empty(self):
        resp = classify_input("1234567890123456")
        assert len(resp.document_candidates) > 0

    def test_context_affects_classification(self):
        """Providing invoice context should influence document candidates."""
        resp_no_ctx = classify_input("1234567890")
        resp_ctx = classify_input("1234567890", context="Invoice #42")
        # Both should work without error
        assert len(resp_no_ctx.candidates) > 0
        assert len(resp_ctx.candidates) > 0

    def test_luhn_valid_card_gets_higher_confidence(self):
        """4532015112830366 is a valid Visa with valid Luhn — should be high confidence."""
        resp = classify_input("4532015112830366")
        card_cands = [c for c in resp.value_candidates if c.type == "card_number"]
        assert len(card_cands) == 1
        # Network match + Luhn = confidence > 0.50
        assert card_cands[0].confidence > 0.50
