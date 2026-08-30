"""CSV / XLSX ingestion: column inspection, numerical column detection."""

from __future__ import annotations

import csv



def read_csv(file_path: str) -> tuple[list[str], list[list[str]]]:
    """Read CSV and return (headers, rows)."""
    with open(file_path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


_MAX_XLSX_ROWS = 200_000  # bound decompressed rows read from the zip container — an
# XLSX is compressed, so a small upload can still unzip to an unbounded row count.


def read_xlsx(file_path: str) -> tuple[list[str], list[list[str]]]:
    """Read XLSX and return (headers, rows)."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        ws = wb.active
        if ws is None:
            return [], []
        headers: list[str] = []
        data: list[list[str]] = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                headers = [str(c) if c is not None else "" for c in row]
                continue
            if i > _MAX_XLSX_ROWS:
                break
            data.append([str(c) if c is not None else "" for c in row])
        wb.close()
        if not headers:
            return [], []
        return headers, data
    except ImportError:
        raise FileNotFoundError(
            "openpyxl is required for XLSX support. Install with: pip install openpyxl"
        )


def detect_numeric_columns(headers: list[str], rows: list[list[str]]) -> dict[str, list[float]]:
    """Inspect columns and return those that parse as numeric."""
    result: dict[str, list[float]] = {}
    for col_idx, header in enumerate(headers):
        values: list[float] = []
        parseable = 0
        for row in rows:
            if col_idx >= len(row):
                continue
            cell = row[col_idx].strip().replace(",", "").replace("$", "").replace("€", "").replace("£", "").replace("₹", "")
            try:
                values.append(float(cell))
                parseable += 1
            except ValueError:
                pass
        if rows and parseable / max(len(rows), 1) > 0.8:
            result[header] = values
    return result


def identify_date_columns(headers: list[str], rows: list[list[str]]) -> set[str]:
    """Identify columns that likely contain dates."""
    import re
    date_pattern = re.compile(
        r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$|^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$"
    )
    date_cols: set[str] = set()
    for col_idx, header in enumerate(headers):
        date_count = 0
        for row in rows[:20]:
            if col_idx < len(row) and date_pattern.match(row[col_idx].strip()):
                date_count += 1
        if date_count > len(rows[:20]) * 0.5:
            date_cols.add(header)
    return date_cols
