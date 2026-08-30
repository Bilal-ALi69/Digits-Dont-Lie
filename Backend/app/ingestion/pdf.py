"""PDF ingestion: text extraction, scanned PDF fallback through OCR."""

from __future__ import annotations



# A malicious or malformed PDF can declare far more pages than its file size
# suggests (a "page bomb") — each OCR'd page costs a full Tesseract pass at
# 200dpi, so an unbounded loop here is a real DoS vector once this endpoint
# is reachable without auth. Cap how many pages the OCR fallback will touch.
_MAX_OCR_PAGES = 25


def extract_text_from_pdf(pdf_path: str) -> tuple[str, bool]:
    """Extract text from a PDF. Falls back to OCR for scanned PDFs.

    Returns (text, exact). `exact` is True when the text came from the PDF's own
    text layer — typeset characters, read losslessly — and False when it came
    from OCR of a scanned page, where the digits were inferred from pixels.
    Callers that verify arithmetic need this distinction: an exact reading can
    support a fraud verdict on its own, an OCR'd one cannot.
    """
    try:
        import pymupdf  # type: ignore[import-untyped]
        doc = pymupdf.open(pdf_path)
        text_parts: list[str] = []
        for page in doc:
            text_parts.append(str(page.get_text("text")))
        doc.close()
        text = "\n".join(text_parts).strip()
        if text:
            return text, True
    except ImportError:
        pass
    except Exception:
        pass

    return _ocr_fallback(pdf_path), False


def _ocr_fallback(pdf_path: str) -> str:
    """Convert PDF pages to images and OCR them."""
    try:
        import pymupdf  # type: ignore[import-untyped]
        from PIL import Image
        import pytesseract  # type: ignore[import-untyped]

        doc = pymupdf.open(pdf_path)
        text_parts: list[str] = []
        page_count = min(len(doc), _MAX_OCR_PAGES)
        for page_num in range(page_count):
            page = doc[page_num]
            pix = page.get_pixmap(dpi=200)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            text = pytesseract.image_to_string(img)
            if text.strip():
                text_parts.append(text)
        doc.close()
        return "\n".join(text_parts).strip()
    except Exception:
        return ""


def extract_tables_from_pdf(pdf_path: str) -> list[list[list[str]]]:
    """Attempt to extract tables from PDF. Returns list of tables, each a list of rows."""
    try:
        import pymupdf  # type: ignore[import-untyped]
        doc = pymupdf.open(pdf_path)
        tables: list[list[list[str]]] = []
        for page in doc:
            tabs = page.find_tables()
            if tabs is None:
                continue
            for tab in tabs.tables:
                table_data = tab.extract()
                tables.append(
                    [[str(cell) if cell is not None else "" for cell in row] for row in table_data]
                )
        doc.close()
        return tables
    except Exception:
        return []
