"""A weak OCR card reading must not shadow a vision transcription.

Reported symptom: three clearly legible sample card images all came back
"insufficient evidence". On stylised card type Tesseract dropped digits and
produced a 13-digit run that matched no card network yet passed Luhn by
coincidence. The vision model was only asked to read the number when OCR found
nothing at all, so that misread won, and _apply_ocr_validation then downgraded
it to insufficient evidence — a card that a person can read at a glance never
got a verdict.
"""

from __future__ import annotations

from unittest.mock import patch

from app.engines.classifier import VisionClassification
from app.ocr import OcrCardCandidate
from app.orchestrator import _analyze_image

CARD_VISION = VisionClassification("credit_card", "card_number", 0.95, "card layout")

# What Tesseract made of the first sample card: digits dropped, no network
# match, but Luhn-valid by coincidence.
WEAK_OCR = OcrCardCandidate(
    digits="2310099991045", luhn_valid=True, network=None,
    variant_agreement=1, total_variants=8,
)
# A clean read of a real-format Visa test pattern that every variant agreed on.
STRONG_OCR = OcrCardCandidate(
    digits="4111111111111111", luhn_valid=True, network="Visa",
    variant_agreement=8, total_variants=8,
)
# What the vision model read off the same card.
VISION_DIGITS = "4532310099991048"


def _run(
    candidate: OcrCardCandidate,
    *,
    vision: VisionClassification | None = CARD_VISION,
    transcription: str | None = VISION_DIGITS,
):
    with patch("app.ocr.extract_text_readings", return_value=["BANK NAME"]), \
         patch("app.ocr.extract_best_card_candidate", return_value=candidate), \
         patch("app.orchestrator._transcribe_card_with_vision",
               return_value=transcription) as transcribe:
        resp = _analyze_image("card.png", prior_vision=vision)
    return resp, transcribe


class TestWeakOcrDefersToVision:
    def test_vision_reading_replaces_weak_ocr_reading(self):
        resp, transcribe = _run(WEAK_OCR)

        assert transcribe.called
        assert resp.extracted_data["source"] == "vision_transcription"
        assert resp.extracted_data["ocr_card_candidate"] == VISION_DIGITS
        assert resp.extracted_data["rejected_ocr_candidate"] == WEAK_OCR.digits

    def test_vision_reading_gets_a_verdict(self):
        """The sample card's digits fail Luhn, which is a verdict — not a shrug."""
        resp, _ = _run(WEAK_OCR)

        assert resp.overall_status.value == "invalid"

    def test_discarded_ocr_reading_is_disclosed(self):
        resp, _ = _run(WEAK_OCR)

        assert any("discarded" in lim for lim in resp.limitations)

    def test_matching_readings_keep_the_ocr_path(self):
        """Vision agreeing with OCR corroborates it; there is nothing to replace."""
        resp, _ = _run(WEAK_OCR, transcription=WEAK_OCR.digits)

        assert resp.extracted_data["source"] == "image_ocr"

    def test_failed_transcription_keeps_the_ocr_path(self):
        resp, _ = _run(WEAK_OCR, transcription=None)

        assert resp.extracted_data["source"] == "image_ocr"


class TestStrongOrUnconfirmedOcrIsLeftAlone:
    def test_strong_ocr_reading_skips_the_vision_call(self):
        """A network match every variant agreed on needs no second opinion."""
        resp, transcribe = _run(STRONG_OCR)

        assert not transcribe.called
        assert resp.extracted_data["source"] == "image_ocr"

    def test_no_vision_means_no_transcription(self):
        """Vision unconfigured or failing: the deterministic path stands alone."""
        _, transcribe = _run(WEAK_OCR, vision=None)

        assert not transcribe.called

    def test_vision_naming_another_document_means_no_transcription(self):
        receipt = VisionClassification("receipt", "currency_amount", 0.9, "receipt")
        _, transcribe = _run(WEAK_OCR, vision=receipt)

        assert not transcribe.called
