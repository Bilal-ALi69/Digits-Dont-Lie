"""Tests for Phase 20: OCR card extraction pipeline."""

from __future__ import annotations

import tempfile
import os
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from app.ocr import (
    create_ocr_variants,
    extract_card_candidates_from_text,
    extract_text_multivariant,
    normalize_ocr_text,
    _luhn_check,
    _detect_card_network,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_image(width: int = 400, height: int = 300) -> str:
    """Create a minimal test image and return its path."""
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    img.save(path)
    return path


# ---------------------------------------------------------------------------
# 1. OCR text normalization
# ---------------------------------------------------------------------------

class TestNormalizeOcrText:
    def test_normalizes_whitespace(self):
        result = normalize_ocr_text("hello    world")
        assert "  " not in result

    def test_preserves_digits(self):
        result = normalize_ocr_text("Card: 4532 0151 1283 0366")
        assert "4532" in result
        assert "0366" in result

    def test_preserves_separators(self):
        result = normalize_ocr_text("4532-0151-1283-0366")
        assert "4532-0151-1283-0366" in result

    def test_handles_newlines(self):
        result = normalize_ocr_text("line1\nline2\nline3")
        assert "line1" in result
        assert "line2" in result

    def test_empty_string(self):
        assert normalize_ocr_text("") == ""

    def test_preserves_currency_symbols(self):
        result = normalize_ocr_text("$1234.56")
        assert "$" in result
        assert "1234" in result


# ---------------------------------------------------------------------------
# 2. Card candidate extraction from text
# ---------------------------------------------------------------------------

class TestExtractCardCandidatesFromText:
    def test_spaces_between_groups(self):
        candidates = extract_card_candidates_from_text("4532 0151 1283 0366")
        assert "4532015112830366" in candidates

    def test_hyphens_between_groups(self):
        candidates = extract_card_candidates_from_text("4532-0151-1283-0366")
        assert "4532015112830366" in candidates

    def test_raw_digits(self):
        candidates = extract_card_candidates_from_text("4532015112830366")
        assert "4532015112830366" in candidates

    def test_split_across_lines(self):
        text = "Card number:\n4532 0151\n1283 0366"
        candidates = extract_card_candidates_from_text(text)
        assert "4532015112830366" in candidates

    def test_split_across_newlines_no_separators(self):
        text = "45320151\n12830366"
        candidates = extract_card_candidates_from_text(text)
        assert "4532015112830366" in candidates

    def test_unrelated_short_numbers_ignored(self):
        text = "Invoice #123456 Amount: $45.99 Date: 2026-01-15"
        candidates = extract_card_candidates_from_text(text)
        for c in candidates:
            assert len(c) >= 13

    def test_multiple_candidates(self):
        text = "Card: 4532015112830366 and 5425233430109903"
        candidates = extract_card_candidates_from_text(text)
        assert "4532015112830366" in candidates
        assert "5425233430109903" in candidates

    def test_empty_text(self):
        candidates = extract_card_candidates_from_text("")
        assert candidates == []

    def test_no_digits(self):
        candidates = extract_card_candidates_from_text("hello world")
        assert candidates == []

    def test_too_short_number(self):
        candidates = extract_card_candidates_from_text("123456789012")
        assert candidates == []

    def test_19_digit_candidate(self):
        text = "1234567890123456789"
        candidates = extract_card_candidates_from_text(text)
        assert "1234567890123456789" in candidates

    def test_mixed_content_with_card(self):
        text = "Visa ending 0366\n4532 0151 1283 0366\nValid thru 12/28"
        candidates = extract_card_candidates_from_text(text)
        assert "4532015112830366" in candidates

    def test_isolated_letter_before_number_not_fabricated_into_extra_digit(self):
        # Regression: a standalone "o" token (common OCR noise from unrelated
        # nearby text, e.g. a logo) was auto-corrected to "0" by digit-fix
        # normalization and then absorbed into an adjacent real card number,
        # fabricating a wrong leading digit ("01083...") instead of the real
        # 16-digit number ("1083...").
        text = "o 1083 3333 0018 0813"
        candidates = extract_card_candidates_from_text(text)
        assert "1083333300180813" in candidates
        assert "01083333300180813" not in candidates


# ---------------------------------------------------------------------------
# 3. Luhn check and network detection
# ---------------------------------------------------------------------------

class TestLuhnCheck:
    def test_valid_visa(self):
        assert _luhn_check("4532015112830366") is True

    def test_valid_amex(self):
        assert _luhn_check("378282246310005") is True

    def test_invalid(self):
        assert _luhn_check("1234567890123456") is False

    def test_too_short(self):
        assert _luhn_check("1234567") is False

    def test_non_digit(self):
        assert _luhn_check("abcdef") is False

    def test_empty(self):
        assert _luhn_check("") is False


class TestDetectCardNetwork:
    def test_visa(self):
        assert _detect_card_network("4532015112830366") == "visa"

    def test_amex(self):
        assert _detect_card_network("378282246310005") == "amex"

    def test_mastercard(self):
        assert _detect_card_network("5425233430109903") == "mastercard"

    def test_unknown(self):
        assert _detect_card_network("1234567890123456") is None


# ---------------------------------------------------------------------------
# 4. Multi-variant preprocessing
# ---------------------------------------------------------------------------

class TestCreateOcrVariants:
    def test_produces_multiple_variants(self):
        img = Image.new("RGB", (800, 600), color=(200, 200, 200))
        variants = create_ocr_variants(img)
        names = [name for name, _ in variants]
        assert "contrast" in names
        assert "threshold" in names

    def test_small_image_gets_upscaled(self):
        """Scaling applies to the shared base, so every variant is enlarged --
        not just one pass out of three, as when it was its own variant."""
        img = Image.new("RGB", (400, 300), color=(200, 200, 200))
        variants = create_ocr_variants(img)

        assert variants
        for name, variant in variants:
            assert variant.width > img.width, f"{name} was not upscaled"

    def test_large_image_not_upscaled(self):
        """An image already at a workable resolution is left alone: resampling
        it would cost time and soften the glyph edges for nothing."""
        img = Image.new("RGB", (2400, 1800), color=(200, 200, 200))
        variants = create_ocr_variants(img)

        assert variants
        for name, variant in variants:
            assert variant.width == img.width, f"{name} was resized"

    def test_threshold_variant_present(self):
        img = Image.new("RGB", (800, 600), color=(200, 200, 200))
        variants = create_ocr_variants(img)
        names = [name for name, _ in variants]
        assert "threshold" in names


# ---------------------------------------------------------------------------
# 5. OCR failure on one variant, fallback to another
# ---------------------------------------------------------------------------

class TestExtractTextMultivariant:
    @patch("app.ocr.pytesseract.image_to_string")
    def test_collects_text_from_multiple_variants(self, mock_ocr):
        call_count = 0

        def side_effect(img, config=""):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return ""
            return "4532 0151 1283 0366"

        mock_ocr.side_effect = side_effect
        path = _make_test_image()
        try:
            text = extract_text_multivariant(path)
            assert "4532" in text
            assert "0366" in text
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_empty_when_all_variants_fail(self, mock_ocr):
        mock_ocr.return_value = ""
        path = _make_test_image()
        try:
            text = extract_text_multivariant(path)
            assert text.strip() == ""
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_exception_on_one_variant_continues(self, mock_ocr):
        call_count = 0

        def side_effect(img, config=""):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Tesseract crashed")
            return "4532015112830366"

        mock_ocr.side_effect = side_effect
        path = _make_test_image()
        try:
            text = extract_text_multivariant(path)
            assert "4532015112830366" in text
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 6. Full image → card engine pipeline (integration with mocked OCR)
# ---------------------------------------------------------------------------

class TestImageCardExtractionPipeline:
    @patch("app.ocr.pytesseract.image_to_string")
    def test_card_number_reaches_card_engine(self, mock_ocr):
        from app.orchestrator import _analyze_image

        call_count = 0

        def side_effect(img, config=""):
            nonlocal call_count
            call_count += 1
            return "4532 0151 1283 0366"

        mock_ocr.side_effect = side_effect
        path = _make_test_image()
        try:
            resp = _analyze_image(path)
            assert resp.input_classification is not None
            assert resp.input_classification.type == "card_number"
            check_names = [c.check for c in resp.checks]
            assert "luhn_checksum" in check_names
            assert "network_detection" in check_names
            assert resp.risk_assessment is not None
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_valid_visa_ocr_reaches_card_engine(self, mock_ocr):
        from app.orchestrator import _analyze_image

        mock_ocr.return_value = "4532 0151 1283 0366"
        path = _make_test_image()
        try:
            resp = _analyze_image(path)
            check_names = [c.check for c in resp.checks]
            assert "luhn_checksum" in check_names
            luhn = next(c for c in resp.checks if c.check == "luhn_checksum")
            assert luhn.status.value == "passed"
            net = next(c for c in resp.checks if c.check == "network_detection")
            assert net.details.get("network") == "visa"
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_invalid_luhn_ocr_reaches_card_engine(self, mock_ocr):
        from app.orchestrator import _analyze_image

        mock_ocr.return_value = "1234 5678 9012 3456"
        path = _make_test_image()
        try:
            resp = _analyze_image(path)
            check_names = [c.check for c in resp.checks]
            assert "luhn_checksum" in check_names
            luhn = next(c for c in resp.checks if c.check == "luhn_checksum")
            assert luhn.status.value == "failed"
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_no_card_candidate_falls_back_to_document(self, mock_ocr):
        from app.orchestrator import _analyze_image

        mock_ocr.return_value = "Invoice #123456 Amount $45.99"
        path = _make_test_image()
        try:
            resp = _analyze_image(path)
            assert resp.input_classification is not None
            assert resp.input_classification.type != "card_number"
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_empty_ocr_returns_insufficient_evidence(self, mock_ocr):
        from app.orchestrator import _analyze_image

        mock_ocr.return_value = ""
        path = _make_test_image()
        try:
            resp = _analyze_image(path)
            from app.models import OverallStatus
            assert resp.overall_status == OverallStatus.INSUFFICIENT_EVIDENCE
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_ocr_candidate_with_hyphens(self, mock_ocr):
        from app.orchestrator import _analyze_image

        mock_ocr.return_value = "4532-0151-1283-0366"
        path = _make_test_image()
        try:
            resp = _analyze_image(path)
            check_names = [c.check for c in resp.checks]
            assert "luhn_checksum" in check_names
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_ocr_candidate_raw_digits(self, mock_ocr):
        from app.orchestrator import _analyze_image

        mock_ocr.return_value = "4532015112830366"
        path = _make_test_image()
        try:
            resp = _analyze_image(path)
            check_names = [c.check for c in resp.checks]
            assert "luhn_checksum" in check_names
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_ocr_card_number_masked_in_extracted_data(self, mock_ocr):
        from app.orchestrator import _analyze_image

        mock_ocr.return_value = "4532 0151 1283 0366"
        path = _make_test_image()
        try:
            resp = _analyze_image(path)
            assert "masked_number" in resp.extracted_data
            assert "0366" in str(resp.extracted_data["masked_number"])
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_classification_source_is_automatic(self, mock_ocr):
        from app.orchestrator import _analyze_image

        mock_ocr.return_value = "4532 0151 1283 0366"
        path = _make_test_image()
        try:
            resp = _analyze_image(path)
            assert resp.classification_source == "automatic"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 7. extract_best_card_candidate
# ---------------------------------------------------------------------------

class TestExtractBestCardCandidate:
    @patch("app.ocr.pytesseract.image_to_string")
    def test_returns_best_scored_candidate(self, mock_ocr):
        from app.ocr import extract_best_card_candidate

        mock_ocr.return_value = "4532 0151 1283 0366"
        path = _make_test_image()
        try:
            result = extract_best_card_candidate(path)
            assert result is not None
            assert result.digits == "4532015112830366"
            assert result.luhn_valid is True
            assert result.network == "visa"
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_returns_none_when_no_candidate(self, mock_ocr):
        from app.ocr import extract_best_card_candidate

        mock_ocr.return_value = "hello world"
        path = _make_test_image()
        try:
            result = extract_best_card_candidate(path)
            assert result is None
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_returns_none_when_empty(self, mock_ocr):
        from app.ocr import extract_best_card_candidate

        mock_ocr.return_value = ""
        path = _make_test_image()
        try:
            result = extract_best_card_candidate(path)
            assert result is None
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_prefers_known_network_candidate(self, mock_ocr):
        from app.ocr import extract_best_card_candidate

        mock_ocr.return_value = "1234567890123456 and 4532015112830366"
        path = _make_test_image()
        try:
            result = extract_best_card_candidate(path)
            assert result is not None
            assert result.digits == "4532015112830366"
            assert result.network == "visa"
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_multiline_card_number(self, mock_ocr):
        from app.ocr import extract_best_card_candidate

        mock_ocr.return_value = "Card No: 4532 0151\n1283 0366"
        path = _make_test_image()
        try:
            result = extract_best_card_candidate(path)
            assert result is not None
            assert result.digits == "4532015112830366"
        finally:
            os.unlink(path)

    def test_scoring_does_not_inflate_consensus_for_a_truncated_prefix(self):
        from app.ocr import _score_card_candidates

        # Two independent OCR passes read the full 16-digit number; a third
        # pass only managed a truncated 13-digit prefix of it. Naive
        # substring-based consensus (checking whether a candidate appears
        # anywhere in a text's raw digit stream) would credit the truncated
        # prefix for "agreeing" with the first two texts as well, since any
        # text containing the full number trivially contains its own prefix
        # — letting an incomplete read outscore the complete, correct one.
        candidates = ["1083333300180813", "1083333300180"]
        unique_texts = [
            "1083 3333 0018 0813",
            "1083 3333 0018 0813",
            "1083 3333 0018 0",
        ]
        scored = _score_card_candidates(candidates, unique_texts)
        assert scored[0][0] == "1083333300180813"


# ---------------------------------------------------------------------------
# 8. Regression: OCR false-positive prevention
# ---------------------------------------------------------------------------

class TestOcrFalsePositivePrevention:
    @patch("app.ocr.pytesseract.image_to_string")
    def test_17digit_unknown_network_not_likely_valid(self, mock_ocr):
        """Regression: 10833333001805313 (17 digits, passes Luhn, unknown
        network) must NOT become likely_valid."""
        from app.orchestrator import _analyze_image
        from app.models import OverallStatus

        mock_ocr.return_value = "1083 3333 0018 05313"
        path = _make_test_image()
        try:
            resp = _analyze_image(path)
            assert resp.overall_status != OverallStatus.LIKELY_VALID
            assert resp.overall_status in (
                OverallStatus.INSUFFICIENT_EVIDENCE,
                OverallStatus.REQUIRES_REVIEW,
                OverallStatus.VALID_WITH_WARNINGS,
            )
            check_names = [c.check for c in resp.checks]
            assert "luhn_checksum" in check_names
            luhn = next(c for c in resp.checks if c.check == "luhn_checksum")
            assert luhn.status.value == "passed"
            net = next(c for c in resp.checks if c.check == "network_detection")
            assert net.status.value == "unknown"
            assert any("does not match" in lim for lim in resp.limitations)
            assert resp.extracted_data.get("ocr_card_candidate") == "10833333001805313"
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_valid_visa_ocr_can_be_likely_valid(self, mock_ocr):
        """Valid Visa with known network + Luhn should pass through."""
        from app.orchestrator import _analyze_image
        from app.models import OverallStatus

        mock_ocr.return_value = "4532 0151 1283 0366"
        path = _make_test_image()
        try:
            resp = _analyze_image(path)
            assert resp.overall_status == OverallStatus.LIKELY_VALID
            net = next(c for c in resp.checks if c.check == "network_detection")
            assert net.details.get("network") == "visa"
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_invalid_luhn_ocr_reaches_card_engine(self, mock_ocr):
        """OCR candidate with invalid Luhn should still show the failure."""
        from app.orchestrator import _analyze_image

        mock_ocr.return_value = "1234 5678 9012 3456"
        path = _make_test_image()
        try:
            resp = _analyze_image(path)
            luhn = next(c for c in resp.checks if c.check == "luhn_checksum")
            assert luhn.status.value == "failed"
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_unknown_network_ocr_gets_limitation(self, mock_ocr):
        """OCR candidate with unknown network should include a limitation."""
        from app.orchestrator import _analyze_image

        mock_ocr.return_value = "1083 3333 0018 05313"
        path = _make_test_image()
        try:
            resp = _analyze_image(path)
            assert any("does not match" in lim for lim in resp.limitations)
            assert any("card network" in lim for lim in resp.limitations)
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_ocr_candidate_metadata_populated(self, mock_ocr):
        """extract_best_card_candidate returns proper metadata."""
        from app.ocr import extract_best_card_candidate

        mock_ocr.return_value = "4532 0151 1283 0366"
        path = _make_test_image()
        try:
            result = extract_best_card_candidate(path)
            assert result is not None
            assert result.digits == "4532015112830366"
            assert result.luhn_valid is True
            assert result.network == "visa"
            assert result.variant_agreement >= 1
            assert result.total_variants >= 1
        finally:
            os.unlink(path)

    def test_manual_confirmed_card_still_works(self):
        """Manually entered confirmed card number is unaffected by OCR gate."""
        from app.orchestrator import analyze_single_value
        from app.models import OverallStatus

        resp = analyze_single_value("4532015112830366", confirmed_value_type="card_number")
        assert resp.overall_status == OverallStatus.LIKELY_VALID
        net = next(c for c in resp.checks if c.check == "network_detection")
        assert net.details.get("network") == "visa"
        luhn = next(c for c in resp.checks if c.check == "luhn_checksum")
        assert luhn.status.value == "passed"

    def test_manual_confirmed_unknown_network_not_affected(self):
        """The OCR gate does NOT apply to manually confirmed numbers.
        Only the OCR path (_analyze_image) applies the validation gate."""
        from app.orchestrator import analyze_single_value
        from app.models import OverallStatus

        resp = analyze_single_value("10833333001805313", confirmed_value_type="card_number")
        assert resp.overall_status == OverallStatus.LIKELY_VALID


# ---------------------------------------------------------------------------
# 9. Phase 21: Fraud verdict as primary outcome
# ---------------------------------------------------------------------------

class TestFraudVerdictPrimaryOutcome:
    def test_valid_card_likely_valid_with_low_risk(self):
        """Valid Visa via manual confirmed path → LIKELY_VALID, risk=0."""
        from app.orchestrator import analyze_single_value
        from app.models import OverallStatus

        resp = analyze_single_value("4532015112830366", confirmed_value_type="card_number")
        assert resp.overall_status == OverallStatus.LIKELY_VALID
        assert resp.risk_assessment is not None
        assert resp.risk_assessment.risk_score == 0
        assert resp.risk_assessment.level == "low"
        luhn = next(c for c in resp.checks if c.check == "luhn_checksum")
        assert luhn.status.value == "passed"
        net = next(c for c in resp.checks if c.check == "network_detection")
        assert net.details.get("network") == "visa"

    def test_invalid_luhn_manual_is_invalid_high_risk(self):
        """Invalid Luhn via manual confirmed path → INVALID, high risk."""
        from app.orchestrator import analyze_single_value
        from app.models import OverallStatus

        resp = analyze_single_value("1234567890123456", confirmed_value_type="card_number")
        assert resp.overall_status == OverallStatus.INVALID
        assert resp.risk_assessment is not None
        assert resp.risk_assessment.risk_score >= 70
        luhn = next(c for c in resp.checks if c.check == "luhn_checksum")
        assert luhn.status.value == "failed"

    @patch("app.ocr.pytesseract.image_to_string")
    def test_ocr_invalid_luhn_is_invalid_high_risk(self, mock_ocr):
        """OCR candidate with invalid Luhn → INVALID, high risk."""
        from app.orchestrator import _analyze_image
        from app.models import OverallStatus

        mock_ocr.return_value = "1234 5678 9012 3456"
        path = _make_test_image()
        try:
            resp = _analyze_image(path)
            assert resp.overall_status == OverallStatus.INVALID
            assert resp.risk_assessment is not None
            assert resp.risk_assessment.risk_score >= 70
            luhn = next(c for c in resp.checks if c.check == "luhn_checksum")
            assert luhn.status.value == "failed"
        finally:
            os.unlink(path)

    def test_ambiguous_non_card_is_insufficient_evidence(self):
        """A number that doesn't match any verification engine → INSUFFICIENT_EVIDENCE."""
        from app.orchestrator import analyze_single_value
        from app.models import OverallStatus

        resp = analyze_single_value("9988776655")
        assert resp.overall_status == OverallStatus.INSUFFICIENT_EVIDENCE

    @patch("app.ocr.pytesseract.image_to_string")
    def test_ocr_valid_visa_is_likely_valid(self, mock_ocr):
        """OCR valid Visa → LIKELY_VALID, risk=0."""
        from app.orchestrator import _analyze_image
        from app.models import OverallStatus

        mock_ocr.return_value = "4532 0151 1283 0366"
        path = _make_test_image()
        try:
            resp = _analyze_image(path)
            assert resp.overall_status == OverallStatus.LIKELY_VALID
            assert resp.risk_assessment is not None
            assert resp.risk_assessment.risk_score == 0
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_ocr_unknown_network_valid_luhn_insufficient(self, mock_ocr):
        """OCR candidate with valid Luhn but unknown network → INSUFFICIENT_EVIDENCE."""
        from app.orchestrator import _analyze_image
        from app.models import OverallStatus

        mock_ocr.return_value = "1083 3333 0018 05313"
        path = _make_test_image()
        try:
            resp = _analyze_image(path)
            assert resp.overall_status == OverallStatus.INSUFFICIENT_EVIDENCE
            assert any("does not match" in lim for lim in resp.limitations)
        finally:
            os.unlink(path)

    @patch("app.ocr.pytesseract.image_to_string")
    def test_ocr_unknown_network_invalid_luhn_is_not_accused(self, mock_ocr):
        """A run failing Luhn AND matching no network is not analysed as a card.

        This previously asserted the opposite — that such an image should reach
        INVALID, on the reasoning that "Luhn failure is the dominant signal". It
        is dominant only once you know the thing is a card. Here nobody has said
        so; the type was guessed from the presence of digits. Long runs of
        unrelated digits are ordinary on real pages, and an invoice printing a
        phone number twice was being reported as a fraudulent credit card.

        Both card checks failing is therefore evidence that it is not a card,
        not evidence that it is a bad one. A user who states the value IS a card
        still gets the definitive verdict — see
        TestFraudVerdictPrimaryOutcome::test_invalid_luhn_manual_is_invalid_high_risk.
        """
        from app.orchestrator import _analyze_image
        from app.models import OverallStatus

        mock_ocr.return_value = "9999 9999 9999 99999"
        path = _make_test_image()
        try:
            resp = _analyze_image(path)
            assert resp.overall_status != OverallStatus.INVALID
            assert "luhn_checksum" not in [c.check for c in resp.checks]
        finally:
            os.unlink(path)

    def test_confirmed_card_runs_card_engine(self):
        """Confirmed card number runs format + Luhn + network checks."""
        from app.orchestrator import analyze_single_value

        resp = analyze_single_value("4532015112830366", confirmed_value_type="card_number")
        check_names = [c.check for c in resp.checks]
        assert "format_length" in check_names
        assert "luhn_checksum" in check_names
        assert "network_detection" in check_names
        assert "masked_number" in resp.extracted_data
