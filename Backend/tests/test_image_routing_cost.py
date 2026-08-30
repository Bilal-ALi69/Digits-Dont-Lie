"""The image pipeline must not pay the card-extraction cost on a document.

Reported symptom: uploading an invoice sat on the loading screen for roughly
half a minute and then returned insufficient evidence. Measured on the two
invoice fixtures, ~12-16s of that was `extract_best_card_candidate` — the
embossed-card digit-line pipeline — running before anything had established
whether the image was a card at all, and a further ~4s was a second full-page
OCR pass repeating work the first had already done.

These tests pin the ordering, not a stopwatch: a wall-clock assertion would be
flaky on shared CI, whereas "the card rescan did not run on a page that
verifies its own arithmetic" is the actual property that makes it fast.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

from PIL import Image

import app.ocr as ocr_module


# A page whose own arithmetic verifies: 145.00 + 9.06 = 154.06.
INVOICE_TEXT = """
ACME SUPPLIES LTD
Invoice #INV-2024-0817        Date: 2024-08-17

Widget assembly            2 x 50.00        100.00
Mounting bracket           3 x 15.00         45.00

                              Subtotal       145.00
                             Tax (6.25%)       9.06
                                 Total       154.06
"""


def _make_image() -> str:
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    Image.new("RGB", (800, 1000), color=(255, 255, 255)).save(path)
    return path


class TestDocumentImageSkipsCardRescan:
    @patch("app.ocr.pytesseract.image_to_string")
    def test_digit_line_rescan_does_not_run_on_a_verifying_document(self, mock_ocr):
        """The rescan re-reads a card-number line. An invoice has none."""
        from app.orchestrator import _analyze_image

        mock_ocr.return_value = INVOICE_TEXT
        path = _make_image()
        try:
            with patch.object(
                ocr_module, "extract_digit_line_candidates", return_value=[]
            ) as rescan:
                _analyze_image(path)
        finally:
            os.unlink(path)

        assert not rescan.called, (
            "the embossed-card digit-line rescan ran on an invoice; it is the "
            "single most expensive step in the upload and cannot find anything here"
        )

    @patch("app.ocr.pytesseract.image_to_string")
    def test_page_is_ocred_once_not_twice(self, mock_ocr):
        """Card extraction and document extraction must share one OCR pass.

        Counts full-page Tesseract invocations rather than calls to a named
        helper: the duplication is two different functions each running their
        own sweep of the same preprocessing variants, which only shows up in
        the pass count.
        """
        from app.orchestrator import _analyze_image

        mock_ocr.return_value = INVOICE_TEXT
        path = _make_image()
        try:
            _analyze_image(path)
        finally:
            os.unlink(path)

        # Two preprocessing variants x two PSM modes is one full sweep.
        assert mock_ocr.call_count <= 4, (
            f"the page was run through Tesseract {mock_ocr.call_count} times; "
            "one sweep of the variants is 4, so the page was read more than once"
        )

    @patch("app.ocr.pytesseract.image_to_string")
    def test_the_invoice_is_still_verified(self, mock_ocr):
        """Skipping the rescan must not cost the verdict it was slowing down."""
        from app.orchestrator import _analyze_image

        mock_ocr.return_value = INVOICE_TEXT
        path = _make_image()
        try:
            resp = _analyze_image(path)
        finally:
            os.unlink(path)

        assert any(c.check == "invoice_totals_consistency" for c in resp.checks), (
            f"checks were {[c.check for c in resp.checks]}"
        )
