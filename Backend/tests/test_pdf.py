"""Tests for PDF ingestion: text extraction, table extraction, and OCR fallback."""

from __future__ import annotations

import os
import tempfile
from unittest import mock

import pytest

pymupdf = pytest.importorskip("pymupdf", reason="pymupdf not installed")

from app.ingestion.pdf import extract_text_from_pdf, extract_tables_from_pdf, _ocr_fallback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_text_pdf(text: str, *, dpi: int = 72) -> str:
    """Create a minimal PDF containing *text* and return its path."""
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()
    return path


def _write_table_pdf() -> str:
    """Create a PDF with a drawn-line table and return its path."""
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    shape = page.new_shape()

    x0, y0 = 72, 72
    col_xs = [0, 120, 240]
    row_ys = [0, 30, 60, 90]

    for dy in row_ys:
        shape.draw_line(
            pymupdf.Point(x0, y0 + dy),
            pymupdf.Point(x0 + 240, y0 + dy),
        )
    for dx in col_xs:
        shape.draw_line(
            pymupdf.Point(x0 + dx, y0),
            pymupdf.Point(x0 + dx, y0 + 90),
        )
    shape.finish(color=(0, 0, 0), width=0.5)
    shape.commit()

    page.insert_text((78, 92), "Name")
    page.insert_text((198, 92), "Value")
    page.insert_text((78, 122), "A")
    page.insert_text((198, 122), "100")
    page.insert_text((78, 152), "B")
    page.insert_text((198, 152), "200")

    doc.save(path)
    doc.close()
    return path


def _write_blank_pdf() -> str:
    """Create a PDF with no text and no tables."""
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)
    doc.save(path)
    doc.close()
    return path


# ---------------------------------------------------------------------------
# 1. Normal text PDF extraction
# ---------------------------------------------------------------------------

class TestExtractTextFromPdf:
    def test_simple_text(self):
        path = _write_text_pdf("Hello World")
        try:
            result, exact = extract_text_from_pdf(path)
            assert isinstance(result, str)
            assert "Hello World" in result
            assert exact is True
        finally:
            os.unlink(path)

    def test_multiline_text(self):
        path = _write_text_pdf("Line one\nLine two\nLine three")
        try:
            result, exact = extract_text_from_pdf(path)
            assert isinstance(result, str)
            assert "Line one" in result
            assert exact is True
            assert "Line two" in result
            assert "Line three" in result
        finally:
            os.unlink(path)

    def test_empty_pdf_falls_back(self):
        path = _write_blank_pdf()
        try:
            result, exact = extract_text_from_pdf(path)
            assert isinstance(result, str)
            # No text layer to read, so whatever came back was OCR'd, not exact.
            assert exact is False
        finally:
            os.unlink(path)

    def test_nonexistent_file_returns_empty(self):
        result, exact = extract_text_from_pdf("/tmp/__nonexistent__.pdf")
        assert result == ""
        assert exact is False


# ---------------------------------------------------------------------------
# 2. PDF with a table
# ---------------------------------------------------------------------------

class TestExtractTablesFromPdf:
    def test_table_detection(self):
        path = _write_table_pdf()
        try:
            tables = extract_tables_from_pdf(path)
            assert isinstance(tables, list)
            assert len(tables) >= 1
            first_table = tables[0]
            assert isinstance(first_table, list)
            assert len(first_table) >= 1
            for row in first_table:
                assert isinstance(row, list)
                for cell in row:
                    assert isinstance(cell, str)
        finally:
            os.unlink(path)

    def test_table_content(self):
        path = _write_table_pdf()
        try:
            tables = extract_tables_from_pdf(path)
            assert len(tables) >= 1
            flat = [cell for row in tables[0] for cell in row]
            assert "Name" in flat
            assert "Value" in flat
        finally:
            os.unlink(path)

    def test_no_tables_in_text_only_pdf(self):
        path = _write_text_pdf("Just some text, no tables here.")
        try:
            tables = extract_tables_from_pdf(path)
            assert isinstance(tables, list)
            assert len(tables) == 0
        finally:
            os.unlink(path)

    def test_blank_pdf_returns_empty(self):
        path = _write_blank_pdf()
        try:
            tables = extract_tables_from_pdf(path)
            assert tables == []
        finally:
            os.unlink(path)

    def test_nonexistent_file_returns_empty(self):
        tables = extract_tables_from_pdf("/tmp/__nonexistent__.pdf")
        assert tables == []


# ---------------------------------------------------------------------------
# 3. Table extraction unavailable / failure path
# ---------------------------------------------------------------------------

class TestTableExtractionFailure:
    def test_find_tables_returns_none(self):
        """Simulate find_tables returning None; should skip gracefully."""
        path = _write_table_pdf()
        try:
            with mock.patch("pymupdf.Page.find_tables", return_value=None):
                tables = extract_tables_from_pdf(path)
                assert tables == []
        finally:
            os.unlink(path)

    def test_extract_raises_exception(self):
        """Simulate Table.extract() raising; should return empty."""
        path = _write_table_pdf()
        try:
            with mock.patch("pymupdf.Page.find_tables") as mock_find:
                mock_finder = mock.MagicMock()
                mock_finder.tables = [mock.MagicMock()]
                mock_finder.tables[0].extract.side_effect = RuntimeError("boom")
                mock_find.return_value = mock_finder
                tables = extract_tables_from_pdf(path)
                assert tables == []
        finally:
            os.unlink(path)

    def test_pymupdf_not_installed(self):
        """Simulate pymupdf import failure in table extraction."""
        with mock.patch.dict("sys.modules", {"pymupdf": None}):
            tables = extract_tables_from_pdf(_write_text_pdf("x"))
            assert tables == []


# ---------------------------------------------------------------------------
# 4. Text normalization / type safety
# ---------------------------------------------------------------------------

class TestTextNormalization:
    def test_get_text_returns_str(self):
        """Ensure extract_text_from_pdf always returns a str, never bytes."""
        path = _write_text_pdf("Numbers: 12345")
        try:
            result, _exact = extract_text_from_pdf(path)
            assert isinstance(result, str)
        finally:
            os.unlink(path)

    def test_table_cells_are_strings(self):
        """Ensure every cell extracted from a table is a plain str."""
        path = _write_table_pdf()
        try:
            tables = extract_tables_from_pdf(path)
            for table in tables:
                for row in table:
                    for cell in row:
                        assert isinstance(cell, str), f"cell is {type(cell)}: {cell!r}"
        finally:
            os.unlink(path)

    def test_get_text_explicit_text_mode(self):
        """Verify the 'text' mode argument produces a clean string."""
        path = _write_text_pdf("Alpha\nBeta")
        try:
            result, _exact = extract_text_from_pdf(path)
            assert isinstance(result, str)
            assert not result.startswith("\x00")
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 5. OCR fallback
# ---------------------------------------------------------------------------

class TestOcrFallback:
    def test_ocr_fallback_returns_str(self):
        """_ocr_fallback should return a string even when OCR fails."""
        path = _write_blank_pdf()
        try:
            result = _ocr_fallback(path)
            assert isinstance(result, str)
        finally:
            os.unlink(path)

    def test_extract_text_falls_back_to_ocr_on_empty(self):
        """When pymupdf extracts empty text, OCR fallback is attempted."""
        path = _write_blank_pdf()
        try:
            with mock.patch(
                "app.ingestion.pdf._ocr_fallback", return_value="OCR_TEXT"
            ):
                result, _exact = extract_text_from_pdf(path)
                assert result == "OCR_TEXT"
        finally:
            os.unlink(path)

    def test_extract_text_skips_ocr_on_success(self):
        """When pymupdf extracts real text, OCR fallback is NOT called."""
        path = _write_text_pdf("Real content")
        try:
            with mock.patch(
                "app.ingestion.pdf._ocr_fallback"
            ) as mock_ocr:
                result, _exact = extract_text_from_pdf(path)
                assert "Real content" in result
                mock_ocr.assert_not_called()
        finally:
            os.unlink(path)

    def test_pymupdf_import_error_triggers_ocr(self):
        """If pymupdf import fails, OCR fallback is used."""
        path = _write_text_pdf("data")
        try:
            with mock.patch.dict("sys.modules", {"pymupdf": None}):
                with mock.patch(
                    "app.ingestion.pdf._ocr_fallback", return_value="FALLBACK"
                ):
                    result, _exact = extract_text_from_pdf(path)
                    assert result == "FALLBACK"
                    assert _exact is False
        finally:
            os.unlink(path)
