"""Tests for input classification."""

from app.engines.classifier import classify_raw_input


class TestClassifier:
    def test_credit_card_like(self):
        result = classify_raw_input("4532015112830366")
        assert result.type == "card_number"

    def test_financial_amount_dollar(self):
        result = classify_raw_input("$1499.00")
        assert result.type == "financial_amount"
        assert result.confidence >= 0.8

    def test_financial_amount_plain(self):
        result = classify_raw_input("1499")
        assert result.type == "financial_amount"

    def test_date_format(self):
        result = classify_raw_input("2026-08-18")
        assert result.type == "date"

    def test_email(self):
        result = classify_raw_input("user@example.com")
        assert result.type == "email"

    def test_url(self):
        result = classify_raw_input("https://example.com")
        assert result.type == "url"

    def test_unknown(self):
        result = classify_raw_input("hello world")
        assert result.type == "unknown"

    def test_has_candidates(self):
        result = classify_raw_input("4532015112830366")
        assert len(result.candidates) > 0
        value_candidates = [c for c in result.candidates if c.layer == "value"]
        assert value_candidates[0].type == "card_number"

    def test_candidates_sorted_by_confidence(self):
        result = classify_raw_input("$1499.00")
        value_candidates = [c for c in result.candidates if c.layer == "value"]
        confidences = [c.confidence for c in value_candidates]
        assert confidences == sorted(confidences, reverse=True)
