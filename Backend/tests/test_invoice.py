"""Tests for invoice/bank-statement field extraction with OCR corroboration."""

from pathlib import Path

import pytest

from app.engines.invoice import extract_invoice_fields, verify_extracted_document
from app.models import CheckStatus, Severity


INVOICE_TEXT = """
ACME SUPPLIES LTD
Invoice #4471

Description            Qty      Amount
Widget A                 2      400.00
Widget B                 1      600.00

                   Subtotal   1,000.00
                        Tax     100.00
                      Total   1,100.00
"""


class TestFieldExtraction:
    def test_extracts_right_aligned_amount_without_currency_symbol(self):
        """The current ocr_enhanced regex requires a currency symbol AND a label
        immediately left of the amount. Real invoices right-align amounts and put
        the symbol in a header, so both assumptions silently drop the total."""
        fields = extract_invoice_fields([INVOICE_TEXT], exact=True)

        assert fields.value_of("total") == 1100.00
        assert fields.value_of("subtotal") == 1000.00
        assert fields.value_of("tax") == 100.00


def _reading_with_total(total: str) -> str:
    """The invoice above, re-rendered with a different reading of the total."""
    return INVOICE_TEXT.replace("1,100.00", total)


class TestCorroboration:
    def test_majority_agreement_corroborates_a_field(self):
        readings = [
            _reading_with_total("1,100.00"),
            _reading_with_total("100.00"),  # OCR dropped the leading 1
            _reading_with_total("1,100.00"),
        ]
        fields = extract_invoice_fields(readings)

        total = fields.fields["total"]
        assert total.value == 1100.00
        assert total.readings_agreeing == 2
        assert total.corroborated is True

    def test_readings_that_all_disagree_are_not_corroborated(self):
        readings = [
            _reading_with_total("1,100.00"),
            _reading_with_total("100.00"),
            _reading_with_total("7,100.00"),
        ]
        fields = extract_invoice_fields(readings)

        assert fields.fields["total"].corroborated is False

    def test_single_ocr_reading_is_never_corroborated(self):
        """One OCR pass agreeing with itself proves nothing."""
        fields = extract_invoice_fields([INVOICE_TEXT])

        assert fields.fields["total"].corroborated is False

    def test_single_exact_reading_is_corroborated(self):
        """A PDF's own text layer was not guessed at, so it needs no second opinion."""
        fields = extract_invoice_fields([INVOICE_TEXT], exact=True)

        assert fields.fields["total"].corroborated is True


# An invoice whose stated total does not match subtotal + tax. If this document
# is read correctly, it is arithmetically impossible and therefore fraudulent.
TAMPERED_TEXT = INVOICE_TEXT.replace("1,100.00", "1,850.00")


class TestTwoTierVerdict:
    def test_corroborated_mismatch_is_a_critical_failure(self):
        """Multiple readings agree on the numbers, and the numbers don't add up.
        This is provable — it is allowed to drive an INVALID verdict."""
        fields = extract_invoice_fields([TAMPERED_TEXT, TAMPERED_TEXT], exact=False)
        checks = verify_extracted_document(fields)

        mismatch = [c for c in checks if c.check == "invoice_totals_consistency"]
        assert len(mismatch) == 1
        assert mismatch[0].status == CheckStatus.FAILED
        assert mismatch[0].severity == Severity.CRITICAL

    def test_uncorroborated_mismatch_never_accuses(self):
        """The numbers don't add up, but the readings disagree about what they
        are — so the mismatch may be a misread. This must NOT reach FAILED."""
        readings = [
            TAMPERED_TEXT,
            _reading_with_total("100.00"),
            INVOICE_TEXT,
        ]
        fields = extract_invoice_fields(readings)
        checks = verify_extracted_document(fields)

        mismatch = [c for c in checks if c.check == "invoice_totals_consistency"]
        assert len(mismatch) == 1
        assert mismatch[0].status == CheckStatus.REQUIRES_REVIEW
        assert mismatch[0].severity != Severity.CRITICAL

    def test_uncorroborated_mismatch_still_shows_the_evidence(self):
        """Downgrading the verdict must not hide what was found."""
        readings = [TAMPERED_TEXT, _reading_with_total("100.00"), INVOICE_TEXT]
        checks = verify_extracted_document(extract_invoice_fields(readings))

        mismatch = [c for c in checks if c.check == "invoice_totals_consistency"][0]
        assert mismatch.details["stated_total"] is not None
        assert mismatch.details["computed_total"] is not None
        assert "agreement" in mismatch.details

    def test_consistent_invoice_passes(self):
        fields = extract_invoice_fields([INVOICE_TEXT], exact=True)
        checks = verify_extracted_document(fields)

        consistency = [c for c in checks if c.check == "invoice_totals_consistency"]
        assert len(consistency) == 1
        assert consistency[0].status == CheckStatus.PASSED

    def test_missing_fields_produce_no_arithmetic_claim(self):
        """A document with no recognisable totals must not be silently passed."""
        checks = verify_extracted_document(
            extract_invoice_fields(["just some prose with no amounts"], exact=True)
        )

        assert not [c for c in checks if c.check == "invoice_totals_consistency"]


STATEMENT_TEXT = """
FIRST NATIONAL BANK
Statement period: 01/03/2026 - 31/03/2026

Opening balance          4,200.00
Total credits            1,500.00
Total debits               900.00
Closing balance          4,800.00
"""


class TestBankStatement:
    def test_consistent_statement_passes(self):
        fields = extract_invoice_fields([STATEMENT_TEXT], exact=True)
        checks = verify_extracted_document(fields)

        balance = [c for c in checks if c.check == "bank_balance"]
        assert len(balance) == 1
        assert balance[0].status == CheckStatus.PASSED

    def test_corroborated_balance_mismatch_fails(self):
        tampered = STATEMENT_TEXT.replace("4,800.00", "9,900.00")
        checks = verify_extracted_document(
            extract_invoice_fields([tampered], exact=True)
        )

        balance = [c for c in checks if c.check == "bank_balance"][0]
        assert balance.status == CheckStatus.FAILED

    def test_uncorroborated_balance_mismatch_never_accuses(self):
        tampered = STATEMENT_TEXT.replace("4,800.00", "9,900.00")
        readings = [tampered, STATEMENT_TEXT, STATEMENT_TEXT.replace("4,800.00", "1,800.00")]
        checks = verify_extracted_document(extract_invoice_fields(readings))

        balance = [c for c in checks if c.check == "bank_balance"][0]
        assert balance.status == CheckStatus.REQUIRES_REVIEW
        assert balance.severity != Severity.CRITICAL


class TestUnreliableReadingsMakeNoClaimEitherWay:
    """The two-tier rule is symmetric. An unreliable reading may not accuse a
    document, and it may not clear one either — if we cannot trust the digits,
    'these numbers add up' is as unsupportable as 'these numbers don't'."""

    def test_uncorroborated_but_consistent_invoice_is_not_passed(self):
        readings = [INVOICE_TEXT, _reading_with_total("1,100.00 ")]
        fields = extract_invoice_fields(readings)
        # Precondition: the arithmetic itself is fine here.
        assert fields.value_of("total") == 1100.00

        fields.fields["total"].readings_agreeing = 1  # simulate a disagreeing pass
        checks = verify_extracted_document(fields)

        consistency = [c for c in checks if c.check == "invoice_totals_consistency"][0]
        assert consistency.status != CheckStatus.PASSED
        assert consistency.status == CheckStatus.REQUIRES_REVIEW

    def test_uncorroborated_but_consistent_statement_is_not_passed(self):
        fields = extract_invoice_fields([STATEMENT_TEXT])
        checks = verify_extracted_document(fields)

        balance = [c for c in checks if c.check == "bank_balance"][0]
        assert balance.status != CheckStatus.PASSED


class TestOrchestratorWiring:
    """End-to-end through the analysis pipeline, which is where this feature
    either exists for users or doesn't."""

    def test_tampered_invoice_text_reaches_an_invalid_verdict(self):
        from app.orchestrator import analyze_document_text
        from app.models import OverallStatus

        resp = analyze_document_text(TAMPERED_TEXT, source_type="pdf", exact=True)

        assert any(c.check == "invoice_totals_consistency" for c in resp.checks)
        assert resp.overall_status == OverallStatus.INVALID
        assert resp.display_status == "INVALID / FRAUD DETECTED"

    def test_genuine_invoice_text_is_not_accused(self):
        from app.orchestrator import analyze_document_text
        from app.models import OverallStatus

        resp = analyze_document_text(INVOICE_TEXT, source_type="pdf", exact=True)

        assert resp.overall_status != OverallStatus.INVALID
        assert resp.display_status != "INVALID / FRAUD DETECTED"

    def test_disagreeing_readings_of_a_tampered_invoice_do_not_accuse(self):
        """The anti-false-positive path, end to end."""
        from app.orchestrator import analyze_document_text
        from app.models import OverallStatus

        resp = analyze_document_text(
            TAMPERED_TEXT,
            source_type="image_ocr",
            readings=[TAMPERED_TEXT, _reading_with_total("100.00"), INVOICE_TEXT],
        )

        assert resp.overall_status != OverallStatus.INVALID
        assert any(c.check == "invoice_totals_consistency" for c in resp.checks)

    def test_invoice_reports_arithmetic_and_declines_benford(self):
        """A single invoice can never be a Benford dataset. Before this work that
        meant no verdict at all was possible; now the arithmetic answers it, and
        the statistical test is recorded as not applicable rather than warning
        about a sample size that was never going to be relevant."""
        from app.orchestrator import analyze_document_text

        resp = analyze_document_text(TAMPERED_TEXT, source_type="pdf", exact=True)
        names = [c.check for c in resp.checks]

        assert "invoice_totals_consistency" in names
        assert "sample_size" not in names
        benford = [c for c in resp.checks if c.check == "benford_applicability"]
        assert len(benford) == 1
        assert benford[0].status == CheckStatus.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# End-to-end: an actual rendered invoice image through the real OCR pipeline.
# This is the path a user exercises by photographing a document, so it is worth
# testing against real Tesseract rather than a mock of it.
# ---------------------------------------------------------------------------

def _render_invoice_image(text: str) -> str:
    import os
    import tempfile
    from PIL import Image, ImageDraw, ImageFont

    font = None
    for candidate in (
        "/usr/share/fonts/noto/NotoSansMono-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/liberation/LiberationMono-Regular.ttf",
    ):
        if os.path.exists(candidate):
            font = ImageFont.truetype(candidate, 28)
            break
    if font is None:
        pytest.skip("no monospace TTF available to render a test invoice")

    lines = text.strip().split("\n")
    img = Image.new("RGB", (900, 60 + 40 * len(lines)), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((30, 30 + 40 * i), line, fill=(0, 0, 0), font=font)

    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    img.save(path)
    return path


class TestPhotographedInvoiceEndToEnd:
    def test_tampered_invoice_image_is_detected(self):
        import os
        from app.orchestrator import analyze_file
        from app.models import OverallStatus

        path = _render_invoice_image(TAMPERED_TEXT)
        try:
            resp = analyze_file(path)
        finally:
            os.unlink(path)

        assert any(c.check == "invoice_totals_consistency" for c in resp.checks), (
            f"no arithmetic check ran; checks were "
            f"{[c.check for c in resp.checks]}, extracted={resp.consistency_analysis}"
        )
        assert resp.overall_status == OverallStatus.INVALID

    def test_genuine_invoice_image_is_not_accused(self):
        import os
        from app.orchestrator import analyze_file
        from app.models import OverallStatus

        path = _render_invoice_image(INVOICE_TEXT)
        try:
            resp = analyze_file(path)
        finally:
            os.unlink(path)

        assert resp.overall_status != OverallStatus.INVALID


class TestPdfTextLayerIsExact:
    """A digital PDF's text layer was typeset, not guessed at. Requiring a second
    OCR pass to corroborate it would make tampered digital invoices unreportable."""

    def test_tampered_digital_pdf_reaches_invalid_from_one_reading(self, monkeypatch):
        import app.ingestion.pdf as pdf_module
        from app.orchestrator import _analyze_pdf
        from app.models import OverallStatus

        monkeypatch.setattr(
            pdf_module, "extract_text_from_pdf", lambda _p: (TAMPERED_TEXT, True)
        )
        resp = _analyze_pdf("/nonexistent/invoice.pdf")

        assert resp.overall_status == OverallStatus.INVALID

    def test_scanned_pdf_falling_back_to_ocr_is_not_exact(self, monkeypatch):
        """When the text came from OCR of a scan, one reading proves nothing."""
        import app.ingestion.pdf as pdf_module
        from app.orchestrator import _analyze_pdf
        from app.models import OverallStatus

        monkeypatch.setattr(
            pdf_module, "extract_text_from_pdf", lambda _p: (TAMPERED_TEXT, False)
        )
        resp = _analyze_pdf("/nonexistent/scan.pdf")

        assert resp.overall_status != OverallStatus.INVALID
        assert any(c.check == "invoice_totals_consistency" for c in resp.checks)


class TestLineItems:
    """Catches the invoice whose stated subtotal and total agree with each other
    but not with the line items above them — padded rows, deleted rows, or a
    subtotal simply typed over."""

    HEADER = ["Description", "Qty", "Amount"]

    def test_line_items_matching_subtotal_pass(self):
        from app.engines.invoice import verify_line_items

        table = [self.HEADER, ["Widget A", "2", "400.00"], ["Widget B", "1", "600.00"]]
        checks = verify_line_items([table], stated_subtotal=1000.00)

        assert len(checks) == 1
        assert checks[0].status == CheckStatus.PASSED

    def test_line_items_contradicting_subtotal_fail(self):
        from app.engines.invoice import verify_line_items

        table = [self.HEADER, ["Widget A", "2", "400.00"], ["Widget B", "1", "600.00"]]
        checks = verify_line_items([table], stated_subtotal=1750.00)

        assert checks[0].status == CheckStatus.FAILED
        assert checks[0].details["computed_subtotal"] == 1000.00

    def test_ambiguous_table_makes_no_claim(self):
        """No identifiable amount column means no check at all. Guessing which
        column holds money is exactly how a tool starts accusing real invoices."""
        from app.engines.invoice import verify_line_items

        table = [["Notes", "Ref"], ["delivered late", "AB-1"], ["backordered", "AB-2"]]
        checks = verify_line_items([table], stated_subtotal=1000.00)

        assert checks == []

    def test_table_without_a_stated_subtotal_makes_no_claim(self):
        from app.engines.invoice import verify_line_items

        table = [self.HEADER, ["Widget A", "2", "400.00"]]
        assert verify_line_items([table], stated_subtotal=None) == []


class TestRealPdfEndToEnd:
    """A genuine digital PDF invoice, read through its own text layer."""

    def _write_invoice_pdf(self, text: str) -> str:
        import os
        import tempfile

        pymupdf = pytest.importorskip("pymupdf", reason="pymupdf not installed")
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        y = 72
        for line in text.strip().split("\n"):
            page.insert_text((72, y), line)
            y += 18
        doc.save(path)
        doc.close()
        return path

    def test_tampered_pdf_invoice_is_detected(self):
        import os
        from app.orchestrator import analyze_file
        from app.models import OverallStatus

        path = self._write_invoice_pdf(TAMPERED_TEXT)
        try:
            resp = analyze_file(path)
        finally:
            os.unlink(path)

        assert resp.overall_status == OverallStatus.INVALID
        assert resp.display_status == "INVALID / FRAUD DETECTED"

    def test_genuine_pdf_invoice_is_not_accused(self):
        import os
        from app.orchestrator import analyze_file
        from app.models import OverallStatus

        path = self._write_invoice_pdf(INVOICE_TEXT)
        try:
            resp = analyze_file(path)
        finally:
            os.unlink(path)

        assert resp.overall_status != OverallStatus.INVALID


class TestLineItemsWiredIntoPdfPath:
    """An invoice can be internally consistent at the bottom and still be padded
    in the middle: subtotal and total agree with each other, but the line items
    above them sum to something else. Only the line-item check sees this."""

    PADDED_INVOICE = """
ACME SUPPLIES LTD
Invoice #4471

                   Subtotal   1,000.00
                        Tax     100.00
                      Total   1,100.00
"""

    def test_padded_line_items_are_caught_even_when_totals_agree(self, monkeypatch):
        import app.ingestion.pdf as pdf_module
        from app.orchestrator import _analyze_pdf
        from app.models import OverallStatus

        monkeypatch.setattr(
            pdf_module, "extract_text_from_pdf", lambda _p: (self.PADDED_INVOICE, True)
        )
        # Line items sum to 700, not the 1,000 subtotal the document claims.
        monkeypatch.setattr(
            pdf_module,
            "extract_tables_from_pdf",
            lambda _p: [[["Description", "Amount"], ["Widget A", "400.00"], ["Widget B", "300.00"]]],
        )
        resp = _analyze_pdf("/nonexistent/padded.pdf")

        line_item_checks = [c for c in resp.checks if c.check == "invoice_line_items"]
        assert len(line_item_checks) == 1
        assert line_item_checks[0].status == CheckStatus.FAILED
        assert resp.overall_status in (OverallStatus.INVALID, OverallStatus.REQUIRES_REVIEW)

    def test_consistent_line_items_do_not_accuse(self, monkeypatch):
        import app.ingestion.pdf as pdf_module
        from app.orchestrator import _analyze_pdf
        from app.models import OverallStatus

        monkeypatch.setattr(
            pdf_module, "extract_text_from_pdf", lambda _p: (self.PADDED_INVOICE, True)
        )
        monkeypatch.setattr(
            pdf_module,
            "extract_tables_from_pdf",
            lambda _p: [[["Description", "Amount"], ["Widget A", "400.00"], ["Widget B", "600.00"]]],
        )
        resp = _analyze_pdf("/nonexistent/clean.pdf")

        line_item_checks = [c for c in resp.checks if c.check == "invoice_line_items"]
        assert len(line_item_checks) == 1
        assert line_item_checks[0].status == CheckStatus.PASSED
        assert resp.overall_status != OverallStatus.INVALID


class TestRateExpressionsAreNotAmounts:
    """Regression: a real invoice writes "Tax (10%)   65.00". Taking the first
    number right of the label captures the *rate*, computes a total that is off
    by the real tax, and reports a genuine invoice as fraud — with every OCR
    pass agreeing, because the error is in the parsing rather than the reading.
    Corroboration cannot catch a mistake all readings make identically."""

    def test_percentage_in_label_is_not_taken_as_the_amount(self):
        fields = extract_invoice_fields(["Tax (10%)        65.00"], exact=True)
        assert fields.value_of("tax") == 65.00

    def test_bare_percentage_yields_no_amount(self):
        fields = extract_invoice_fields(["Tax rate 10%"], exact=True)
        assert fields.value_of("tax") is None

    def test_rightmost_monetary_amount_wins_over_a_trailing_date(self):
        fields = extract_invoice_fields(["Total    715.00    paid 03/14"], exact=True)
        assert fields.value_of("total") == 715.00

    def test_discount_percentage_does_not_become_a_discount_amount(self):
        fields = extract_invoice_fields(["Discount (5%)      32.50"], exact=True)
        assert fields.value_of("discount") == 32.50

    def test_realistic_invoice_with_a_tax_rate_is_consistent(self):
        text = """
                    Subtotal       650.00
                  Tax (10%)        65.00
                       Total       715.00
"""
        checks = verify_extracted_document(extract_invoice_fields([text], exact=True))
        consistency = [c for c in checks if c.check == "invoice_totals_consistency"][0]
        assert consistency.status == CheckStatus.PASSED


class TestLowResolutionDocument:
    """Regression, from a real invoice that failed in the app.

    A full-page invoice saved at screen resolution (465x659, roughly 60 DPI) is
    the ordinary case for a downloaded or emailed invoice, and OCR wants ~300
    DPI. The old fixed 2x upscale was sized for close-up card crops: it lifted
    this page only to 930x1318, enough to read the large TOTAL but not the
    smaller "Subtotal" line. With no subtotal, the arithmetic check had nothing
    to verify and silently never ran, so the document fell through to Benford --
    which then flagged the 69 numbers on the page as anomalous.

    The fixture is the exact image that produced that result.
    """

    FIXTURE = Path(__file__).parent / "fixtures" / "invoice_low_res.png"

    def _readings(self) -> list[str]:
        from app.ocr import extract_text_readings

        if not self.FIXTURE.exists():
            pytest.skip("fixture image missing")
        return extract_text_readings(str(self.FIXTURE))

    def test_totals_block_is_recovered(self):
        fields = extract_invoice_fields(self._readings())

        assert fields.value_of("subtotal") == 145.00, f"read: {fields.fields}"
        assert fields.value_of("tax") == 9.06, f"read: {fields.fields}"
        assert fields.value_of("total") == 154.06, f"read: {fields.fields}"

    def test_genuine_invoice_reaches_a_passing_arithmetic_check(self):
        """145.00 + 9.06 = 154.06. The document is correct and must be seen to be."""
        checks = verify_extracted_document(extract_invoice_fields(self._readings()))

        consistency = [c for c in checks if c.check == "invoice_totals_consistency"]
        assert len(consistency) == 1, f"no arithmetic check ran; checks={checks}"
        assert consistency[0].status == CheckStatus.PASSED

    def test_end_to_end_verdict_is_not_an_accusation(self):
        from app.orchestrator import analyze_file
        from app.models import OverallStatus

        if not self.FIXTURE.exists():
            pytest.skip("fixture image missing")
        resp = analyze_file(str(self.FIXTURE))

        assert any(c.check == "invoice_totals_consistency" for c in resp.checks), (
            f"checks were {[c.check for c in resp.checks]}"
        )
        assert resp.overall_status != OverallStatus.INVALID


class TestIdenticalReadingsCorroborate:
    """Two preprocessing passes producing byte-identical text is the strongest
    corroboration available, not the weakest.

    `_extract_unique_texts` deduplicates, because its original caller wanted
    varied candidates to score. Reusing it to measure agreement inverted the
    signal: clean, unambiguous OCR collapsed to a single reading and so counted
    as uncorroborated, meaning the clearer the photograph the less likely the
    system was to reach a verdict on it.
    """

    def test_readings_are_not_deduplicated(self):
        import os
        from app.ocr import extract_text_readings
        from app.ocr import create_ocr_variants
        from PIL import Image

        path = _render_invoice_image(INVOICE_TEXT)
        try:
            variants = len(create_ocr_variants(Image.open(path)))
            readings = extract_text_readings(path)
        finally:
            os.unlink(path)

        assert len(readings) == variants, (
            f"{variants} variants produced {len(readings)} readings — identical "
            f"passes were collapsed, destroying the agreement signal"
        )

    def test_cleanly_read_tampered_invoice_is_corroborated(self):
        import os
        from app.ocr import extract_text_readings

        path = _render_invoice_image(TAMPERED_TEXT)
        try:
            readings = extract_text_readings(path)
        finally:
            os.unlink(path)

        fields = extract_invoice_fields(readings)
        assert fields.fields["total"].corroborated is True, (
            f"read {fields.fields['total']}"
        )


class TestBenfordIsScopedToDatasets:
    """Benford's Law describes naturally-occurring datasets spanning orders of
    magnitude. The numbers scraped off a single invoice are zip codes, dates,
    a P.O. number and a handful of quantities — not a comparable dataset — so a
    chi-square over them measures nothing, and on a provably correct invoice it
    reported 'anomalous' and outvoted the arithmetic that had a real answer.

    It is skipped for documents that verify themselves arithmetically, and says
    so as a not-applicable check rather than vanishing silently. Everywhere else
    — datasets, and documents with no invoice structure — it is unchanged.
    """

    # Invoice structure plus well over Benford's 50-value minimum.
    NUMERIC_INVOICE = (
        "ACME LTD  Invoice 4471\n"
        + "\n".join(f"Item {i}  qty {i}  ref 2019{i:02d}  {i * 7}.00" for i in range(1, 40))
        + "\n           Subtotal   1,000.00\n"
        "                Tax     100.00\n"
        "              Total   1,100.00\n"
    )

    def test_benford_does_not_run_on_a_self_verifying_document(self):
        from app.orchestrator import analyze_document_text

        resp = analyze_document_text(self.NUMERIC_INVOICE, source_type="pdf", exact=True)
        names = [c.check for c in resp.checks]

        assert "benford_chi_square" not in names, f"checks: {names}"
        assert "sample_size" not in names, f"checks: {names}"

    def test_the_skip_is_stated_rather_than_silent(self):
        """A judge reading the report must see that Benford was considered and
        why it was set aside, not merely find it absent."""
        from app.orchestrator import analyze_document_text

        resp = analyze_document_text(self.NUMERIC_INVOICE, source_type="pdf", exact=True)

        skipped = [c for c in resp.checks if c.check == "benford_applicability"]
        assert len(skipped) == 1, f"checks: {[c.check for c in resp.checks]}"
        assert skipped[0].status == CheckStatus.NOT_APPLICABLE
        assert skipped[0].severity == Severity.NONE
        assert "invoice" in skipped[0].message.lower() or "document" in skipped[0].message.lower()

    def test_a_correct_invoice_now_reaches_a_clean_verdict(self):
        from app.orchestrator import analyze_document_text
        from app.models import OverallStatus

        resp = analyze_document_text(self.NUMERIC_INVOICE, source_type="pdf", exact=True)

        assert resp.overall_status == OverallStatus.LIKELY_VALID
        assert resp.display_status == "LIKELY VALID"
        assert resp.risk_assessment is not None
        assert resp.risk_assessment.risk_score == 0

    def test_benford_still_runs_on_a_document_without_invoice_structure(self):
        """The scoping is narrow: no subtotal/total pair means no arithmetic to
        rely on, so the statistical test remains the only thing available."""
        from app.orchestrator import analyze_document_text

        text = "\n".join(f"reading {i}  {i * 13}.00" for i in range(1, 60))
        resp = analyze_document_text(text, source_type="pdf", exact=True)
        names = [c.check for c in resp.checks]

        assert "benford_chi_square" in names, f"checks: {names}"

    def test_real_invoice_image_reaches_a_clean_verdict(self):
        from app.orchestrator import analyze_file
        from app.models import OverallStatus

        fixture = Path(__file__).parent / "fixtures" / "invoice_low_res.png"
        if not fixture.exists():
            pytest.skip("fixture image missing")
        resp = analyze_file(str(fixture))

        assert resp.overall_status == OverallStatus.LIKELY_VALID, (
            f"status={resp.overall_status} checks={[(c.check, c.status.value) for c in resp.checks]}"
        )


class TestDocumentClassification:
    """The document path never set a classification, so the frontend fell through
    to its `unknown -> "id"` default and announced a scanned invoice as an
    "ID Number". A page that states a subtotal and a total has told us what it
    is; there is no need to guess, and no excuse for guessing wrong."""

    def test_invoice_text_is_classified_as_an_invoice(self):
        from app.orchestrator import analyze_document_text

        resp = analyze_document_text(INVOICE_TEXT, source_type="pdf", exact=True)

        assert resp.top_document_type == "invoice"
        assert resp.input_classification is not None
        assert resp.input_classification.type == "invoice"

    def test_statement_text_is_classified_as_a_bank_statement(self):
        from app.orchestrator import analyze_document_text

        resp = analyze_document_text(STATEMENT_TEXT, source_type="pdf", exact=True)

        assert resp.top_document_type == "bank_statement"

    def test_classification_carries_a_document_candidate(self):
        """The UI lists candidates; a document should appear among them as what
        it is, rather than the list being empty and the label being inferred."""
        from app.orchestrator import analyze_document_text

        resp = analyze_document_text(INVOICE_TEXT, source_type="pdf", exact=True)

        assert any(c.type == "invoice" and c.layer == "document" for c in resp.document_candidates)

    def test_plain_document_text_is_not_claimed_to_be_an_invoice(self):
        """No self-verifying structure means no claim about the document type."""
        from app.orchestrator import analyze_document_text

        resp = analyze_document_text("just some prose, nothing numeric", source_type="pdf", exact=True)

        assert resp.top_document_type != "invoice"

    def test_real_invoice_image_is_classified_as_an_invoice(self):
        from app.orchestrator import analyze_file

        fixture = Path(__file__).parent / "fixtures" / "invoice_low_res.png"
        if not fixture.exists():
            pytest.skip("fixture image missing")
        resp = analyze_file(str(fixture))

        assert resp.top_document_type == "invoice", (
            f"got {resp.top_document_type!r}; classification="
            f"{resp.input_classification.type if resp.input_classification else None}"
        )


class TestSplitDecimalsAreRepaired:
    """OCR frequently breaks a decimal point away from its digits: "145.00" is
    read as "145 .00". The amount pattern then matches "145" and "00" as two
    separate figures, and rightmost-wins picks the "00" — reporting a subtotal
    of 0.00. Two passes splitting it the same way would agree on that, so
    corroboration would confirm the wrong number rather than catch it.
    """

    def test_a_split_decimal_is_read_as_one_amount(self):
        fields = extract_invoice_fields(["Subtotal 145 .00"], exact=True)
        assert fields.value_of("subtotal") == 145.00

    def test_a_space_after_the_point_is_repaired_too(self):
        fields = extract_invoice_fields(["Total 154. 06"], exact=True)
        assert fields.value_of("total") == 154.06

    def test_split_decimals_do_not_break_the_arithmetic(self):
        text = "Subtotal 145 .00\nSales Tax 6.25% 9 .06\nTOTAL 154 .06"
        checks = verify_extracted_document(extract_invoice_fields([text], exact=True))

        consistency = [c for c in checks if c.check == "invoice_totals_consistency"][0]
        assert consistency.status == CheckStatus.PASSED, consistency.details

    def test_genuinely_separate_numbers_are_still_separate(self):
        """The repair must not glue unrelated figures together: a quantity and
        an amount separated by whitespace are two numbers, not one."""
        fields = extract_invoice_fields(["Total   2   1500.00"], exact=True)
        assert fields.value_of("total") == 1500.00


class TestDigitSoupIsNotACard:
    """A digit run that fails Luhn *and* matches no card network is not a card
    number by any measure available, so it must not claim the whole document.

    Real pages produce these constantly: an invoice printing a phone number
    twice yields a long run of digits, and OCR concatenates them. Vision would
    normally overrule it, but vision is an optional external service — when it
    is unconfigured, rate-limited or down, that guard silently disappears and
    the page gets analysed as a payment card.
    """

    def test_a_run_failing_both_checks_does_not_claim_the_page(self):
        from app.orchestrator import _should_treat_as_card
        from app.ocr import OcrCardCandidate

        soup = OcrCardCandidate(
            digits="1234567890123534567",
            luhn_valid=False,
            network=None,
            variant_agreement=1,
            total_variants=2,
        )
        assert _should_treat_as_card(soup, has_document_structure=False) is False

    def test_a_real_card_still_claims_the_page(self):
        from app.orchestrator import _should_treat_as_card
        from app.ocr import OcrCardCandidate

        visa = OcrCardCandidate(
            digits="4532015112830366",
            luhn_valid=True,
            network="visa",
            variant_agreement=2,
            total_variants=2,
        )
        assert _should_treat_as_card(visa, has_document_structure=False) is True

    def test_a_luhn_valid_run_with_no_network_is_still_considered(self):
        """Luhn passing is real evidence, so this one keeps the card path —
        _apply_ocr_validation downgrades its verdict rather than the routing."""
        from app.orchestrator import _should_treat_as_card
        from app.ocr import OcrCardCandidate

        odd = OcrCardCandidate(
            digits="10833333001805313",
            luhn_valid=True,
            network=None,
            variant_agreement=2,
            total_variants=2,
        )
        assert _should_treat_as_card(odd, has_document_structure=False) is True

    def test_an_invoice_always_wins_over_a_weak_candidate(self):
        from app.orchestrator import _should_treat_as_card
        from app.ocr import OcrCardCandidate

        odd = OcrCardCandidate(
            digits="10833333001805313",
            luhn_valid=True,
            network=None,
            variant_agreement=2,
            total_variants=2,
        )
        assert _should_treat_as_card(odd, has_document_structure=True) is False

    def test_the_real_template_is_not_reported_as_a_card(self):
        import os
        from app.orchestrator import analyze_file

        fixture = Path(__file__).parent / "fixtures" / "invoice_blank_template.jpeg"
        if not fixture.exists():
            pytest.skip("fixture missing")
        resp = analyze_file(str(fixture))

        names = [c.check for c in resp.checks]
        assert "luhn_checksum" not in names, f"analysed as a card; checks={names}"
