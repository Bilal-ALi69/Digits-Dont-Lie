"""Improved OCR with contextual number extraction."""

from __future__ import annotations

import re

from app.models import Evidence, CheckCategory, CheckStatus


_CURRENCY_SYMBOLS = re.compile(r"[\$£€₹]")
_CURRENCY_NUMBER_RE = re.compile(r"[\$£€₹]\s?-?\d[\d,]*\.?\d*")
_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")
_DATE_RE = re.compile(
    r"\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b|\b\d{4}[/\-]\d{1,2}[/\-]\d{1,2}\b"
)


def extract_contextual_numbers(text: str) -> dict[str, list[str]]:
    """Extract numbers with their surrounding context."""
    lines = text.split("\n")
    currency_amounts: list[str] = []
    all_numbers: list[str] = []
    labeled_amounts: dict[str, float] = {}

    for line in lines:
        for match in _CURRENCY_NUMBER_RE.finditer(line):
            raw = match.group()
            cleaned = raw.lstrip("$£€₹").strip().replace(",", "")
            try:
                val = float(cleaned)
                currency_amounts.append(raw)
                label_match = re.search(
                    r"(subtotal|total|tax|discount|amount|price|balance|debit|credit)[:\s]*$",
                    line[:match.start()],
                    re.IGNORECASE,
                )
                if label_match:
                    labeled_amounts[label_match.group(1).lower()] = val
            except ValueError:
                pass

        for match in _NUMBER_RE.finditer(line):
            all_numbers.append(match.group())

    return {
        "currency_amounts": currency_amounts,
        "all_numbers": all_numbers,
        "labeled_amounts": [f"{k}: {v}" for k, v in labeled_amounts.items()],
    }


def extract_dates(text: str) -> list[str]:
    return _DATE_RE.findall(text)


def extract_table_rows(text: str) -> list[list[str]]:
    """Attempt to detect tabular data from OCR text."""
    lines = text.split("\n")
    tables: list[list[str]] = []
    current_table: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if len(current_table) >= 3:
                tables.append([r for r in current_table])
            current_table = []
            continue
        parts = re.split(r"\s{2,}|\t", stripped)
        if len(parts) >= 2:
            current_table.append(stripped)
        else:
            if len(current_table) >= 3:
                tables.append([r for r in current_table])
            current_table = []
    if len(current_table) >= 3:
        tables.append(current_table)
    return tables
