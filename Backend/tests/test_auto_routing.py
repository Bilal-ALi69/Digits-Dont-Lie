"""Tests for Phase 19: Automatic classification to verification pipeline routing."""

from unittest.mock import MagicMock, patch

from app.models import OverallStatus
from app.orchestrator import analyze_single_value, classify_input

AUTH = {"X-API-Key": "test-api-key-for-ci"}


class TestRegressionAutoCardViaAPI:
    """Regression: POST /api/analyze with only value+input_type must auto-route card."""

    def test_auto_card_no_confirmation(self):
        from fastapi.testclient import TestClient
        from app.api.server import app

        client = TestClient(app)
        resp = client.post("/api/analyze", json={
            "value": "4532015112830366",
            "input_type": "auto",
        }, headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["classification_source"] == "automatic"
        assert data["top_value_type"] == "card_number"
        assert len(data["checks"]) > 0
        assert data["risk_assessment"] is not None
        assert data["overall_status"] == "likely_valid"
        check_names = [c["check"] for c in data["checks"]]
        assert "format_length" in check_names
        assert "luhn_checksum" in check_names
        assert "network_detection" in check_names


class TestHighConfidenceAutomaticCard:
    """Test A: High-confidence automatic card classification."""

    def test_valid_visa_auto_routes_to_card_engine(self):
        resp = analyze_single_value("4532015112830366")
        assert resp.classification_source == "automatic"
        assert resp.top_value_type == "card_number"
        assert resp.top_document_type == "credit_card"
        check_names = [c.check for c in resp.checks]
        assert "format_length" in check_names
        assert "luhn_checksum" in check_names
        assert "network_detection" in check_names

    def test_valid_visa_has_risk_assessment(self):
        resp = analyze_single_value("4532015112830366")
        assert resp.risk_assessment is not None

    def test_valid_visa_overall_not_insufficient(self):
        resp = analyze_single_value("4532015112830366")
        assert resp.overall_status != OverallStatus.INSUFFICIENT_EVIDENCE

    def test_valid_visa_preserves_candidates(self):
        resp = analyze_single_value("4532015112830366")
        assert len(resp.value_candidates) > 0
        assert len(resp.document_candidates) > 0
        value_types = [c.type for c in resp.value_candidates]
        doc_types = [c.type for c in resp.document_candidates]
        assert "card_number" in value_types
        assert "credit_card" in doc_types

    def test_valid_mastercard_auto_routes(self):
        resp = analyze_single_value("5425233430109903")
        assert resp.classification_source == "automatic"
        assert resp.top_value_type == "card_number"
        check_names = [c.check for c in resp.checks]
        assert "luhn_checksum" in check_names

    def test_valid_amex_auto_routes(self):
        resp = analyze_single_value("378282246310005")
        assert resp.classification_source == "automatic"
        assert resp.top_value_type == "card_number"
        check_names = [c.check for c in resp.checks]
        assert "luhn_checksum" in check_names

    def test_valid_visa_luhn_passes(self):
        resp = analyze_single_value("4532015112830366")
        luhn = next(c for c in resp.checks if c.check == "luhn_checksum")
        assert luhn.status.value == "passed"

    def test_valid_visa_network_detected(self):
        resp = analyze_single_value("4532015112830366")
        net = next(c for c in resp.checks if c.check == "network_detection")
        assert net.details.get("network") == "visa"

    def test_valid_visa_masked_number_in_extracted(self):
        resp = analyze_single_value("4532015112830366")
        assert "masked_number" in resp.extracted_data


class TestConfirmedCard:
    """Test B: Confirmed card input."""

    def test_confirmed_valid_card(self):
        resp = analyze_single_value(
            "4532015112830366",
            confirmed_document_type="credit_card",
            confirmed_value_type="card_number",
        )
        assert resp.classification_source == "confirmed"
        check_names = [c.check for c in resp.checks]
        assert "format_length" in check_names
        assert "luhn_checksum" in check_names
        assert "network_detection" in check_names
        assert resp.risk_assessment is not None
        luhn = next(c for c in resp.checks if c.check == "luhn_checksum")
        assert luhn.status.value == "passed"

    def test_confirmed_invalid_card_luhn_fails(self):
        resp = analyze_single_value(
            "1234567890123456",
            confirmed_document_type="credit_card",
            confirmed_value_type="card_number",
        )
        assert resp.classification_source == "confirmed"
        check_names = [c.check for c in resp.checks]
        assert "luhn_checksum" in check_names
        luhn = next(c for c in resp.checks if c.check == "luhn_checksum")
        assert luhn.status.value == "failed"
        assert resp.overall_status == OverallStatus.INVALID
        assert resp.risk_assessment is not None

    def test_confirmed_card_stores_document_type(self):
        resp = analyze_single_value(
            "4532015112830366",
            confirmed_document_type="debit_card",
            confirmed_value_type="card_number",
        )
        assert resp.extracted_data.get("document_type") == "debit_card"


class TestAmbiguousInput:
    """Test C: Ambiguous input should NOT blindly assume card."""

    def test_ambiguous_16_digits_not_assumed_card(self):
        resp = analyze_single_value("1234567890123456")
        assert resp.classification_source == "automatic"
        assert resp.overall_status == OverallStatus.INSUFFICIENT_EVIDENCE
        check_names = [c.check for c in resp.checks]
        assert "luhn_checksum" not in check_names
        assert "network_detection" not in check_names

    def test_ambiguous_preserves_candidates(self):
        resp = analyze_single_value("1234567890123456")
        assert len(resp.value_candidates) > 0
        assert len(resp.document_candidates) > 0

    def test_ambiguous_has_limitations(self):
        resp = analyze_single_value("1234567890123000")
        assert len(resp.limitations) > 0

    def test_unknown_text_insufficient_evidence(self):
        resp = analyze_single_value("hello world")
        assert resp.overall_status == OverallStatus.INSUFFICIENT_EVIDENCE
        assert resp.classification_source == "automatic"


class TestConfirmationOverridesAmbiguity:
    """Test D: Confirmation overrides ambiguous auto-classification."""

    def test_confirmed_overrides_ambiguous_card(self):
        resp = analyze_single_value(
            "1234567890123456",
            confirmed_document_type="credit_card",
            confirmed_value_type="card_number",
        )
        assert resp.classification_source == "confirmed"
        check_names = [c.check for c in resp.checks]
        assert "luhn_checksum" in check_names
        assert "network_detection" in check_names

    def test_confirmed_financial_overrides_ambiguous(self):
        resp = analyze_single_value("12500", confirmed_value_type="financial_amount")
        assert resp.classification_source == "confirmed"
        assert "value" in resp.extracted_data
        assert resp.overall_status == OverallStatus.INSUFFICIENT_EVIDENCE

    def test_confirmed_generic_identifier(self):
        resp = analyze_single_value("123456789", confirmed_value_type="generic_identifier")
        assert resp.classification_source == "confirmed"
        check_names = [c.check for c in resp.checks]
        assert "luhn_checksum" not in check_names
        assert any("identifier" in c.message.lower() for c in resp.checks)

    def test_legacy_confirmed_type_overrides(self):
        resp = analyze_single_value("1234567890123456", confirmed_type="card_number")
        assert resp.classification_source == "confirmed"
        check_names = [c.check for c in resp.checks]
        assert "luhn_checksum" in check_names


class TestGroqBehavior:
    """Test E & F: Groq integration behavior."""

    def test_groq_failure_deterministic_still_works(self):
        with patch("app.orchestrator.get_groq_client") as mock_get:
            mock_client = MagicMock()
            mock_client.available = False
            mock_get.return_value = mock_client
            resp = analyze_single_value("4532015112830366")
            assert resp.overall_status != OverallStatus.INSUFFICIENT_EVIDENCE
            check_names = [c.check for c in resp.checks]
            assert "luhn_checksum" in check_names

    def test_groq_timeout_no_crash(self):
        with patch("app.orchestrator.get_groq_client") as mock_get:
            mock_client = MagicMock()
            mock_client.chat.side_effect = TimeoutError("timeout")
            mock_get.return_value = mock_client
            resp = analyze_single_value("4532015112830366")
            assert resp.overall_status != OverallStatus.INSUFFICIENT_EVIDENCE
            check_names = [c.check for c in resp.checks]
            assert "luhn_checksum" in check_names

    def test_groq_invalid_enum_rejected(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = '{"value_type": "malicious_type", "document_type": "malicious_doc"}'
        with patch("app.orchestrator.get_groq_client", return_value=mock_client):
            resp = analyze_single_value("12345678")
            value_types = [c.type for c in resp.value_candidates]
            doc_types = [c.type for c in resp.document_candidates]
            assert "malicious_type" not in value_types
            assert "malicious_doc" not in doc_types

    def test_groq_none_response_no_crash(self):
        mock_client = MagicMock()
        mock_client.chat.return_value = None
        with patch("app.orchestrator.get_groq_client", return_value=mock_client):
            resp = analyze_single_value("1234567890123456")
            assert resp.input_classification is not None

    def test_groq_enhanced_explanation_with_available_client(self):
        with patch("app.orchestrator.get_groq_client") as mock_get:
            mock_client = MagicMock()
            mock_client.available = True
            mock_client.chat.return_value = "AI explanation."
            mock_get.return_value = mock_client
            resp = analyze_single_value("4532015112830366")
            assert resp.explanation == "AI explanation."


class TestClassificationSource:
    """Test that classification_source is correctly set."""

    def test_automatic_when_no_confirmation(self):
        resp = analyze_single_value("4532015112830366")
        assert resp.classification_source == "automatic"

    def test_confirmed_when_value_type_provided(self):
        resp = analyze_single_value("4532015112830366", confirmed_value_type="card_number")
        assert resp.classification_source == "confirmed"

    def test_confirmed_when_document_type_provided(self):
        resp = analyze_single_value("4532015112830366", confirmed_document_type="credit_card")
        assert resp.classification_source == "confirmed"

    def test_confirmed_when_legacy_type_provided(self):
        resp = analyze_single_value("4532015112830366", confirmed_type="card_number")
        assert resp.classification_source == "confirmed"


class TestCandidatePreservation:
    """Test that candidates are preserved in the response."""

    def test_candidates_in_response(self):
        resp = analyze_single_value("4532015112830366")
        assert hasattr(resp, "value_candidates")
        assert hasattr(resp, "document_candidates")
        assert hasattr(resp, "top_value_type")
        assert hasattr(resp, "top_document_type")
        assert len(resp.value_candidates) > 0
        assert len(resp.document_candidates) > 0
        assert resp.top_value_type != ""
        assert resp.top_document_type != ""

    def test_all_candidates_preserved_not_just_top(self):
        resp = analyze_single_value("4532015112830366")
        value_types = [c.type for c in resp.value_candidates]
        assert len(value_types) > 1 or value_types[0] == "card_number"

    def test_candidates_in_api_response(self):
        from fastapi.testclient import TestClient
        from app.api.server import app
        client = TestClient(app)
        resp = client.post("/api/analyze", json={
            "input_type": "auto",
            "value": "4532015112830366",
        }, headers=AUTH)
        data = resp.json()
        assert "value_candidates" in data
        assert "document_candidates" in data
        assert "top_value_type" in data
        assert "top_document_type" in data
        assert "classification_source" in data
        assert len(data["value_candidates"]) > 0

    def test_classification_source_in_api_response(self):
        from fastapi.testclient import TestClient
        from app.api.server import app
        client = TestClient(app)
        resp = client.post("/api/analyze", json={
            "input_type": "auto",
            "value": "4532015112830366",
        }, headers=AUTH)
        data = resp.json()
        assert data["classification_source"] == "automatic"

    def test_confirmed_source_in_api_response(self):
        from fastapi.testclient import TestClient
        from app.api.server import app
        client = TestClient(app)
        resp = client.post("/api/analyze", json={
            "input_type": "auto",
            "value": "4532015112830366",
            "confirmed_value_type": "card_number",
        }, headers=AUTH)
        data = resp.json()
        assert data["classification_source"] == "confirmed"


class TestEdgeCases:
    """Edge cases for the routing pipeline."""

    def test_short_number_insufficient(self):
        resp = analyze_single_value("12345")
        assert resp.overall_status == OverallStatus.INSUFFICIENT_EVIDENCE

    def test_single_digit_insufficient(self):
        resp = analyze_single_value("5")
        assert resp.overall_status == OverallStatus.INSUFFICIENT_EVIDENCE

    def test_currency_high_confidence_routes(self):
        resp = analyze_single_value("$1499.00")
        assert resp.classification_source == "automatic"
        assert resp.top_value_type == "financial_amount"

    def test_date_high_confidence_routes(self):
        resp = analyze_single_value("2026-08-18")
        assert resp.classification_source == "automatic"
        assert resp.top_value_type == "date"
        check_names = [c.check for c in resp.checks]
        assert "date_format" in check_names

    def test_email_high_confidence_routes(self):
        resp = analyze_single_value("user@test.com")
        assert resp.classification_source == "automatic"
        assert resp.top_value_type == "email"

    def test_url_high_confidence_routes(self):
        resp = analyze_single_value("https://example.com")
        assert resp.classification_source == "automatic"
        assert resp.top_value_type == "url"
