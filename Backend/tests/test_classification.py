"""Tests for Phase 17: Intelligent Classification, Confidence Ranking, and User Override."""

import json
from unittest.mock import MagicMock, patch

from app.engines.classifier import classify_raw_input, classify_with_candidates
from app.orchestrator import analyze_single_value, classify_input

AUTH = {"X-API-Key": "test-api-key-for-ci"}


class TestCardClassification:
    def test_valid_visa_ranked_first(self):
        candidates = classify_with_candidates("4532015112830366")
        value_candidates = [c for c in candidates if c.layer == "value"]
        assert value_candidates[0].type == "card_number"
        assert value_candidates[0].confidence > 0.6
        assert "visa" in value_candidates[0].reason.lower()

    def test_valid_mastercard_ranked_first(self):
        candidates = classify_with_candidates("5425233430109903")
        value_candidates = [c for c in candidates if c.layer == "value"]
        assert value_candidates[0].type == "card_number"
        assert value_candidates[0].confidence > 0.6

    def test_invalid_luhn_reduces_confidence(self):
        valid = classify_with_candidates("4532015112830366")
        invalid = classify_with_candidates("4532015112830367")
        valid_val = [c for c in valid if c.layer == "value" and c.type == "card_number"]
        invalid_val = [c for c in invalid if c.layer == "value" and c.type == "card_number"]
        assert valid_val[0].confidence > invalid_val[0].confidence
        assert "invalid luhn" in invalid_val[0].reason.lower()

    def test_formatted_with_spaces(self):
        candidates = classify_with_candidates("4532 0151 1283 0366")
        value_candidates = [c for c in candidates if c.layer == "value"]
        assert value_candidates[0].type == "card_number"
        assert "separator" in value_candidates[0].reason.lower() or "formatted" in value_candidates[0].reason.lower()

    def test_formatted_with_hyphens(self):
        candidates = classify_with_candidates("4532-0151-1283-0366")
        value_candidates = [c for c in candidates if c.layer == "value"]
        assert value_candidates[0].type == "card_number"

    def test_amex_15_digits(self):
        candidates = classify_with_candidates("378282246310005")
        value_candidates = [c for c in candidates if c.layer == "value"]
        assert value_candidates[0].type == "card_number"
        assert "amex" in value_candidates[0].reason.lower()

    def test_short_number_not_card(self):
        candidates = classify_with_candidates("12345")
        value_candidates = [c for c in candidates if c.layer == "value"]
        assert value_candidates[0].type != "card_number"


class TestAmbiguousNumbers:
    def test_generic_numeric_identifier(self):
        candidates = classify_with_candidates("987654")
        value_candidates = [c for c in candidates if c.layer == "value"]
        types = [c.type for c in value_candidates]
        assert "generic_identifier" in types

    def test_financial_amount_with_currency(self):
        candidates = classify_with_candidates("$12500")
        value_candidates = [c for c in candidates if c.layer == "value"]
        assert value_candidates[0].type == "financial_amount"
        assert value_candidates[0].confidence > 0.8

    def test_financial_amount_plain_number(self):
        candidates = classify_with_candidates("12500")
        value_candidates = [c for c in candidates if c.layer == "value"]
        types = [c.type for c in value_candidates]
        assert "financial_amount" in types

    def test_date_classification(self):
        candidates = classify_with_candidates("2026-01-15")
        value_candidates = [c for c in candidates if c.layer == "value"]
        assert value_candidates[0].type == "date"

    def test_email_classification(self):
        candidates = classify_with_candidates("user@test.com")
        value_candidates = [c for c in candidates if c.layer == "value"]
        assert value_candidates[0].type == "email"

    def test_url_classification(self):
        candidates = classify_with_candidates("https://example.com")
        value_candidates = [c for c in candidates if c.layer == "value"]
        assert value_candidates[0].type == "url"

    def test_unknown_text(self):
        candidates = classify_with_candidates("hello world")
        value_candidates = [c for c in candidates if c.layer == "value"]
        assert value_candidates[0].type == "unknown"


class TestContextSupport:
    def test_invoice_context_boosts_reference(self):
        without_ctx = classify_with_candidates("784512369")
        with_ctx = classify_with_candidates("784512369", context="Invoice #784512369")
        ref_without = next((c for c in without_ctx if c.layer == "value" and c.type == "invoice_number"), None)
        ref_with = next((c for c in with_ctx if c.layer == "value" and c.type == "invoice_number"), None)
        assert ref_with is not None
        assert ref_with.confidence > 0.5

    def test_amount_context_boosts_financial(self):
        without_ctx = classify_with_candidates("12500")
        with_ctx = classify_with_candidates("12500", context="Amount Due: 12,500")
        fin_without = next((c for c in without_ctx if c.layer == "value" and c.type == "financial_amount"), None)
        fin_with = next((c for c in with_ctx if c.layer == "value" and c.type == "financial_amount"), None)
        assert fin_without is not None
        assert fin_with is not None
        assert fin_with.confidence > fin_without.confidence

    def test_unrelated_context_no_boost(self):
        without_ctx = classify_with_candidates("4532015112830366")
        with_ctx = classify_with_candidates("4532015112830366", context="weather forecast today")
        without_val = [c for c in without_ctx if c.layer == "value"]
        with_val = [c for c in with_ctx if c.layer == "value"]
        assert without_val[0].type == "card_number"
        assert with_val[0].type == "card_number"
        assert abs(without_val[0].confidence - with_val[0].confidence) < 0.05

    def test_transaction_context(self):
        candidates = classify_with_candidates("TXN884521", context="Transaction ID: TXN884521")
        assert candidates is not None

    def test_invoice_context_adds_document_type(self):
        candidates = classify_with_candidates("784512369", context="Invoice #784512369")
        doc_candidates = [c for c in candidates if c.layer == "document"]
        doc_types = [c.type for c in doc_candidates]
        assert "invoice" in doc_types


class TestUserOverride:
    def test_confirmed_type_overrides_card(self):
        resp = analyze_single_value("4532015112830366", confirmed_type="invoice_number")
        check_names = [c.check for c in resp.checks]
        assert "luhn_checksum" not in check_names
        assert "network_detection" not in check_names
        # Asserts the *human* form. This previously required the raw
        # "invoice_number" token to appear in the message, which encoded the
        # very bug it now guards: internal value-type identifiers were being
        # interpolated straight into check messages and rendered verbatim in
        # the results list ("Value treated as generic_identifier.").
        assert any("invoice number" in c.message for c in resp.checks)
        assert not any("invoice_number" in c.message for c in resp.checks)

    def test_confirmed_financial_amount(self):
        resp = analyze_single_value("12500", confirmed_type="financial_amount")
        assert "value" in resp.extracted_data
        assert resp.overall_status.value == "insufficient_evidence"

    def test_confirmed_card_runs_luhn(self):
        resp = analyze_single_value("4532015112830366", confirmed_type="card_number")
        check_names = [c.check for c in resp.checks]
        assert "luhn_checksum" in check_names
        assert "network_detection" in check_names

    def test_no_confirmed_type_uses_auto(self):
        resp = analyze_single_value("4532015112830366")
        check_names = [c.check for c in resp.checks]
        assert "luhn_checksum" in check_names

    def test_confirmed_generic_identifier(self):
        resp = analyze_single_value("123456789", confirmed_type="generic_identifier")
        check_names = [c.check for c in resp.checks]
        assert "luhn_checksum" not in check_names
        assert any("identifier" in c.message.lower() for c in resp.checks)

    def test_confirmed_value_type_overrides(self):
        resp = analyze_single_value("4532015112830366", confirmed_value_type="invoice_number")
        check_names = [c.check for c in resp.checks]
        assert "luhn_checksum" not in check_names

    def test_confirmed_document_type_stored(self):
        resp = analyze_single_value("4532015112830366", confirmed_document_type="debit_card")
        assert resp.extracted_data.get("document_type") == "debit_card"


class TestClassifyInput:
    def test_returns_classification_response(self):
        resp = classify_input("4532015112830366")
        assert resp.recommended_type == "card_number"
        assert len(resp.value_candidates) > 0
        assert resp.input_value != ""

    def test_masked_card_in_response(self):
        resp = classify_input("4532015112830366")
        assert "0366" in resp.input_value
        assert "4532" not in resp.input_value

    def test_non_card_not_masked(self):
        resp = classify_input("$1499.00")
        assert "$1499.00" in resp.input_value

    def test_context_passed_through(self):
        resp = classify_input("784512369", context="Invoice #784512369")
        assert resp.recommended_type is not None
        assert len(resp.value_candidates) > 0

    def test_document_candidates_populated(self):
        resp = classify_input("4532015112830366")
        assert len(resp.document_candidates) > 0
        assert resp.top_document_type != ""

    def test_value_candidates_populated(self):
        resp = classify_input("4532015112830366")
        assert len(resp.value_candidates) > 0
        assert resp.top_value_type == "card_number"

    def test_backward_compat_candidates(self):
        resp = classify_input("4532015112830366")
        assert len(resp.candidates) > 0
        assert resp.recommended_type == resp.top_value_type


class TestGroqClassification:
    def test_groq_adds_candidate_for_ambiguous(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = json.dumps({
            "value_type": "invoice_number",
            "document_type": "invoice",
        })
        candidates = classify_with_candidates("12345678", groq_client=mock_client)
        value_candidates = [c for c in candidates if c.layer == "value"]
        types = [c.type for c in value_candidates]
        assert "invoice_number" in types
        mock_client.chat.assert_called_once()

    def test_groq_not_called_when_confident(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = json.dumps({
            "value_type": "card_number",
            "document_type": "credit_card",
        })
        candidates = classify_with_candidates("4532015112830366", groq_client=mock_client)
        mock_client.chat.assert_not_called()
        value_candidates = [c for c in candidates if c.layer == "value"]
        assert value_candidates[0].type == "card_number"

    def test_groq_unavailable_no_crash(self):
        candidates = classify_with_candidates("12345678")
        assert len(candidates) > 0

    def test_groq_timeout_no_crash(self):
        mock_client = MagicMock()
        mock_client.chat.side_effect = TimeoutError("timeout")
        candidates = classify_with_candidates("12345678", groq_client=mock_client)
        assert len(candidates) > 0

    def test_groq_malformed_response(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = "I don't understand"
        candidates = classify_with_candidates("12345678", groq_client=mock_client)
        assert len(candidates) > 0

    def test_groq_none_response(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = None
        candidates = classify_with_candidates("12345678", groq_client=mock_client)
        assert len(candidates) > 0

    def test_groq_agrees_boosts_existing(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = json.dumps({
            "value_type": "financial_amount",
            "document_type": "other",
        })
        candidates = classify_with_candidates("12500", groq_client=mock_client)
        fin = next((c for c in candidates if c.layer == "value" and c.type == "financial_amount"), None)
        assert fin is not None
        assert "groq" in fin.reason.lower()

    def test_groq_rejects_non_enum_value_type(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = json.dumps({
            "value_type": "malicious_type",
            "document_type": "other",
        })
        candidates = classify_with_candidates("12345678", groq_client=mock_client)
        value_candidates = [c for c in candidates if c.layer == "value"]
        types = [c.type for c in value_candidates]
        assert "malicious_type" not in types

    def test_groq_rejects_non_enum_document_type(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = json.dumps({
            "value_type": "unknown",
            "document_type": "malicious_doc",
        })
        candidates = classify_with_candidates("12345678", groq_client=mock_client)
        doc_candidates = [c for c in candidates if c.layer == "document"]
        types = [c.type for c in doc_candidates]
        assert "malicious_doc" not in types

    def test_groq_json_with_markdown_wrapper(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = '```json\n{"value_type": "invoice_number", "document_type": "invoice"}\n```'
        candidates = classify_with_candidates("12345678", groq_client=mock_client)
        value_candidates = [c for c in candidates if c.layer == "value"]
        types = [c.type for c in value_candidates]
        assert "invoice_number" in types

    def test_groq_produces_both_layers(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = json.dumps({
            "value_type": "card_number",
            "document_type": "credit_card",
        })
        candidates = classify_with_candidates("12345678", groq_client=mock_client)
        doc_candidates = [c for c in candidates if c.layer == "document"]
        value_candidates = [c for c in candidates if c.layer == "value"]
        assert len(doc_candidates) > 0
        assert len(value_candidates) > 0


class TestAPIEndpoints:
    def test_classify_endpoint(self):
        from fastapi.testclient import TestClient
        from app.api.server import app
        client = TestClient(app)
        resp = client.post("/api/classify", json={"value": "4532015112830366"}, headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["recommended_type"] == "card_number"
        assert len(data["value_candidates"]) > 0

    def test_classify_with_context(self):
        from fastapi.testclient import TestClient
        from app.api.server import app
        client = TestClient(app)
        resp = client.post("/api/classify", json={
            "value": "784512369",
            "context": "Invoice #784512369",
        }, headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["value_candidates"]) > 0

    def test_analyze_with_confirmed_type(self):
        from fastapi.testclient import TestClient
        from app.api.server import app
        client = TestClient(app)
        resp = client.post("/api/analyze", json={
            "input_type": "auto",
            "value": "4532015112830366",
            "confirmed_type": "invoice_number",
        }, headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        check_names = [c["check"] for c in data["checks"]]
        assert "luhn_checksum" not in check_names

    def test_analyze_with_confirmed_value_type(self):
        from fastapi.testclient import TestClient
        from app.api.server import app
        client = TestClient(app)
        resp = client.post("/api/analyze", json={
            "input_type": "auto",
            "value": "4532015112830366",
            "confirmed_value_type": "invoice_number",
        }, headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        check_names = [c["check"] for c in data["checks"]]
        assert "luhn_checksum" not in check_names

    def test_analyze_with_confirmed_document_type(self):
        from fastapi.testclient import TestClient
        from app.api.server import app
        client = TestClient(app)
        resp = client.post("/api/analyze", json={
            "input_type": "auto",
            "value": "4532015112830366",
            "confirmed_document_type": "debit_card",
        }, headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["extracted_data"].get("document_type") == "debit_card"

    def test_analyze_backward_compat(self):
        from fastapi.testclient import TestClient
        from app.api.server import app
        client = TestClient(app)
        resp = client.post("/api/analyze", json={
            "input_type": "auto",
            "value": "4532015112830366",
        }, headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        check_names = [c["check"] for c in data["checks"]]
        assert "luhn_checksum" in check_names

    def test_health_unchanged(self):
        from fastapi.testclient import TestClient
        from app.api.server import app
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestConfidenceNormalization:
    def test_top_confidence_capped(self):
        candidates = classify_with_candidates("4532015112830366")
        for c in candidates:
            assert c.confidence <= 0.98

    def test_candidates_sorted_descending(self):
        candidates = classify_with_candidates("4532015112830366")
        for c in candidates:
            assert c.layer in ("value", "document")
        value_candidates = [c for c in candidates if c.layer == "value"]
        for i in range(len(value_candidates) - 1):
            assert value_candidates[i].confidence >= value_candidates[i + 1].confidence

    def test_all_confidences_non_negative(self):
        candidates = classify_with_candidates("anything")
        for c in candidates:
            assert 0.0 <= c.confidence <= 0.98


class TestDocumentTypeClassification:
    def test_card_context_produces_credit_card_document(self):
        candidates = classify_with_candidates("4532015112830366")
        doc_candidates = [c for c in candidates if c.layer == "document"]
        doc_types = [c.type for c in doc_candidates]
        assert "credit_card" in doc_types

    def test_debit_context_produces_debit_card_document(self):
        candidates = classify_with_candidates("4532015112830366", context="Debit Card: 4532015112830366")
        doc_candidates = [c for c in candidates if c.layer == "document"]
        doc_types = [c.type for c in doc_candidates]
        assert "debit_card" in doc_types

    def test_invoice_context_produces_invoice_document(self):
        candidates = classify_with_candidates("784512369", context="Invoice #784512369")
        doc_candidates = [c for c in candidates if c.layer == "document"]
        doc_types = [c.type for c in doc_candidates]
        assert "invoice" in doc_types

    def test_receipt_context_produces_receipt_document(self):
        candidates = classify_with_candidates("TXN884521", context="Receipt: Transaction TXN884521")
        doc_candidates = [c for c in candidates if c.layer == "document"]
        doc_types = [c.type for c in doc_candidates]
        assert "receipt" in doc_types

    def test_bank_statement_context(self):
        candidates = classify_with_candidates("12500", context="Bank Statement Account Balance")
        doc_candidates = [c for c in candidates if c.layer == "document"]
        doc_types = [c.type for c in doc_candidates]
        assert "bank_statement" in doc_types

    def test_passport_context(self):
        candidates = classify_with_candidates("AB1234567", context="Passport Number: AB1234567")
        doc_candidates = [c for c in candidates if c.layer == "document"]
        doc_types = [c.type for c in doc_candidates]
        assert "passport" in doc_types

    def test_driver_license_context(self):
        candidates = classify_with_candidates("D1234567", context="Driver License: D1234567")
        doc_candidates = [c for c in candidates if c.layer == "document"]
        doc_types = [c.type for c in doc_candidates]
        assert "driver_license" in doc_types

    def test_no_context_defaults_to_other(self):
        candidates = classify_with_candidates("hello world")
        doc_candidates = [c for c in candidates if c.layer == "document"]
        assert doc_candidates[0].type == "other"


# ---------------------------------------------------------------------------
# Two-stage classify → confirm flow (classification_id)
# ---------------------------------------------------------------------------

class TestClassificationIdFlow:
    """Tests for the classification_id token that links /api/classify to /api/analyze."""

    def test_classify_returns_classification_id(self):
        resp = classify_input("4532015112830366")
        assert resp.classification_id != ""

    def test_confirm_with_valid_id_and_type(self):
        """classify → confirm with a type from the candidate list succeeds."""
        from fastapi.testclient import TestClient
        from app.api.server import app
        client = TestClient(app)

        # Step 1: classify
        classify_resp = client.post(
            "/api/classify",
            json={"value": "4532015112830366"},
            headers=AUTH,
        )
        assert classify_resp.status_code == 200
        cid = classify_resp.json()["classification_id"]
        assert cid != ""

        # Step 2: confirm with card_number (which is in the candidate list)
        analyze_resp = client.post(
            "/api/analyze",
            json={
                "input_type": "auto",
                "value": "4532015112830366",
                "classification_id": cid,
                "confirmed_value_type": "card_number",
            },
            headers=AUTH,
        )
        assert analyze_resp.status_code == 200

    def test_confirm_with_type_not_in_candidates(self):
        """Confirming a type that wasn't in the classification candidates → 400."""
        from fastapi.testclient import TestClient
        from app.api.server import app
        client = TestClient(app)

        # Classify a card number
        classify_resp = client.post(
            "/api/classify",
            json={"value": "4532015112830366"},
            headers=AUTH,
        )
        cid = classify_resp.json()["classification_id"]

        # Try to confirm with an unrelated type
        analyze_resp = client.post(
            "/api/analyze",
            json={
                "input_type": "auto",
                "value": "4532015112830366",
                "classification_id": cid,
                "confirmed_value_type": "email",
            },
            headers=AUTH,
        )
        assert analyze_resp.status_code == 400
        assert "email" in analyze_resp.json()["detail"]

    def test_confirm_with_unknown_id(self):
        """Confirming with a classification_id that doesn't exist → 400."""
        from fastapi.testclient import TestClient
        from app.api.server import app
        client = TestClient(app)

        resp = client.post(
            "/api/analyze",
            json={
                "input_type": "auto",
                "value": "4532015112830366",
                "classification_id": "nonexistent-token-abc123",
                "confirmed_value_type": "card_number",
            },
            headers=AUTH,
        )
        assert resp.status_code == 400
        assert "Unknown" in resp.json()["detail"] or "expired" in resp.json()["detail"]

    def test_confirm_with_no_id_still_works(self):
        """Backward compat: confirmed_value_type without classification_id → 200."""
        from fastapi.testclient import TestClient
        from app.api.server import app
        client = TestClient(app)

        resp = client.post(
            "/api/analyze",
            json={
                "input_type": "auto",
                "value": "4532015112830366",
                "confirmed_value_type": "card_number",
            },
            headers=AUTH,
        )
        assert resp.status_code == 200

    def test_confirm_document_type_with_valid_id(self):
        """Confirming confirmed_document_type against stored candidates."""
        from fastapi.testclient import TestClient
        from app.api.server import app
        client = TestClient(app)

        classify_resp = client.post(
            "/api/classify",
            json={"value": "4532015112830366"},
            headers=AUTH,
        )
        cid = classify_resp.json()["classification_id"]

        # credit_card should be in the document candidates for a Visa number
        analyze_resp = client.post(
            "/api/analyze",
            json={
                "input_type": "auto",
                "value": "4532015112830366",
                "classification_id": cid,
                "confirmed_document_type": "credit_card",
            },
            headers=AUTH,
        )
        assert analyze_resp.status_code == 200

    def test_id_only_no_confirmed_type_passes_through(self):
        """classification_id without any confirmed type is a no-op (no validation)."""
        from fastapi.testclient import TestClient
        from app.api.server import app
        client = TestClient(app)

        resp = client.post(
            "/api/analyze",
            json={
                "input_type": "auto",
                "value": "4532015112830366",
                "classification_id": "any-id-here",
            },
            headers=AUTH,
        )
        assert resp.status_code == 200
