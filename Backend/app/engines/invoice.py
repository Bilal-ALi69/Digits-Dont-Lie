"""Invoice and bank-statement field extraction with OCR corroboration.

The arithmetic in `financial.py` is exact: given the right numbers it is never
wrong. All of the uncertainty in verifying a photographed document lives one
step earlier, in whether OCR read the right digits. This module is that step.

It extracts labeled amounts from one or more *independent readings* of the same
document and reports, for each field, how many readings agreed. A caller can
then distinguish a mismatch it can prove from one that might just be a misread —
the difference between accusing a document and asking a human to look at it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field

from app.engines.financial import verify_bank_balance, verify_invoice_totals
from app.models import CheckCategory, CheckStatus, Evidence, Severity


# Matches financial.py: rounding noise on a legitimate document is cents, not units.
_TOLERANCE = 0.02


# Amount forms this must handle, all seen on real invoices:
#   $1,240.00   1,240.00   1240.00   1240   240.5
# The currency symbol is optional on purpose: invoices routinely print the
# symbol once in a column header and bare numbers in the rows beneath it.
_AMOUNT_RE = re.compile(r"[$£€₹]?\s?-?\d[\d,]*(?:\.\d+)?")

# Label -> the field it populates.
#
# Order matters and is a correctness requirement, not a style choice: exactly one
# label claims each line, and the first match in this dict wins. A bank statement
# line reading "Total credits   1,500.00" contains the word "total", and without
# `credits` being tried first it would be captured as an invoice grand total and
# then checked against arithmetic it has nothing to do with. The specific labels
# therefore precede the generic ones.
#
# ("Subtotal" needs no such care — there is no word boundary between "sub" and
# "total", so the word-bounded `total` pattern cannot match inside it.)
_LABEL_PATTERNS: dict[str, re.Pattern[str]] = {
    "opening": re.compile(r"\b(?:opening|brought\s+forward|b/f|previous)\b", re.IGNORECASE),
    "closing": re.compile(r"\b(?:closing|carried\s+forward|c/f|ending)\b", re.IGNORECASE),
    "credits": re.compile(r"\b(?:credits?|deposits?|money\s+in|paid\s+in)\b", re.IGNORECASE),
    "debits": re.compile(r"\b(?:debits?|withdrawals?|money\s+out|paid\s+out)\b", re.IGNORECASE),
    "subtotal": re.compile(r"\b(?:sub[\s-]?total|net(?:\s+amount)?)\b", re.IGNORECASE),
    "discount": re.compile(r"\b(?:discount|less)\b", re.IGNORECASE),
    "tax": re.compile(r"\b(?:tax|vat|gst|sales\s+tax)\b", re.IGNORECASE),
    "total": re.compile(r"\b(?:grand[\s-]?total|total(?:\s+due)?|amount\s+due|balance\s+due)\b", re.IGNORECASE),
}


def _parse_amount(raw: str) -> float | None:
    cleaned = raw.strip().lstrip("$£€₹").strip().replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _is_percentage(line: str, match: re.Match[str]) -> bool:
    """True when this number is a rate, not a sum of money.

    "Tax (10%)  65.00" is the common shape, and reading the 10 as the tax amount
    understates the tax by exactly the real figure — producing a total that looks
    deliberately falsified on an invoice that is perfectly correct.
    """
    return line[match.end():match.end() + 2].lstrip().startswith("%")


# A figure written like money: a decimal fraction, a thousands separator, or an
# explicit currency symbol. Used to prefer 715.00 over the 03 and 14 of a date
# sitting further right on the same line.
_MONETARY_RE = re.compile(r"[$£€₹]|\d,\d{3}|\.\d{1,2}\b")


def _amount_right_of(line: str, start: int) -> float | None:
    """The amount belonging to a label whose match ended at `start`.

    Invoices right-align their money column, so the rightmost monetary figure on
    the line is the label's amount. Rates are excluded outright, and a plain
    integer is only accepted when the line offers nothing money-shaped.
    """
    monetary: list[float] = []
    plain: list[float] = []

    for match in _AMOUNT_RE.finditer(line, start):
        if _is_percentage(line, match):
            continue
        value = _parse_amount(match.group())
        if value is None:
            continue
        (monetary if _MONETARY_RE.search(match.group()) else plain).append(value)

    if monetary:
        return monetary[-1]
    return plain[-1] if plain else None


@dataclass
class FieldReading:
    """One extracted field, with how well the readings agreed on it."""

    value: float
    readings_agreeing: int
    readings_total: int
    exact: bool = False

    @property
    def agreement(self) -> float:
        if self.readings_total == 0:
            return 0.0
        return self.readings_agreeing / self.readings_total

    @property
    def corroborated(self) -> bool:
        """Whether this value is trustworthy enough to accuse a document over.

        Exact text was never guessed at, so it stands on its own. An OCR reading
        needs a second, independently preprocessed pass to agree with it — one
        pass agreeing with itself proves nothing.
        """
        if self.exact:
            return True
        return self.readings_agreeing >= 2


@dataclass
class InvoiceFields:
    fields: dict[str, FieldReading] = dataclass_field(default_factory=dict)

    def value_of(self, name: str) -> float | None:
        reading = self.fields.get(name)
        return reading.value if reading else None

    def document_kind(self) -> str | None:
        """Which kind of financial document these fields describe, if any.

        Derived from which labels actually matched rather than guessed from the
        page's appearance: a subtotal paired with a total is an invoice, an
        opening balance paired with a closing one is a statement. Returns None
        when the page said neither, so callers make no claim rather than a
        default one.
        """
        if "subtotal" in self.fields and "total" in self.fields:
            return "invoice"
        if "opening" in self.fields and "closing" in self.fields:
            return "bank_statement"
        return None

    def has_document_structure(self) -> bool:
        """Whether the page states figures that verify against each other.

        This is what makes a page an invoice or a statement rather than a
        picture with numbers on it, and it is deliberately the same condition
        the verifier requires: if the arithmetic can run, the document is real
        enough to be routed as one.
        """
        return self.document_kind() is not None


# OCR routinely detaches a decimal point from its digits, turning "145.00" into
# "145 .00" or "154. 06". Left alone the amount pattern reads those as two
# separate figures and the rightmost-wins rule picks the fragment — a subtotal
# of 145.00 becomes 0.00. Only whitespace immediately adjacent to a point that
# already sits between digits is closed up, so genuinely separate numbers on the
# same line (a quantity beside an amount) are untouched.
_SPLIT_DECIMAL_RE = re.compile(r"(?<=\d)\s+\.\s*(?=\d)|(?<=\d)\.\s+(?=\d)")


def _repair_split_decimals(line: str) -> str:
    return _SPLIT_DECIMAL_RE.sub(".", line)


def _extract_from_single_reading(text: str) -> dict[str, float]:
    """Pull labeled amounts out of one reading of a document."""
    found: dict[str, float] = {}

    for raw_line in text.split("\n"):
        line = _repair_split_decimals(raw_line)
        for name, pattern in _LABEL_PATTERNS.items():
            label_match = pattern.search(line)
            if not label_match:
                continue
            # The amount belongs to this label only if it sits to its right —
            # this is what makes right-aligned invoice layouts work, where the
            # label and its amount are separated by a run of whitespace.
            value = _amount_right_of(line, label_match.end())
            if value is not None:
                found[name] = value
            # One label per line: the first (most specific) match claims it.
            break

    return found


def extract_invoice_fields(readings: list[str], *, exact: bool = False) -> InvoiceFields:
    """Extract labeled amounts from N independent readings of one document.

    `exact=True` marks the text as digital-native (a PDF's own text layer, not
    OCR), where a single reading is authoritative because nothing was guessed.
    """
    per_reading = [_extract_from_single_reading(text) for text in readings]
    total_readings = len(per_reading)

    result = InvoiceFields()
    for name in _LABEL_PATTERNS:
        values = [r[name] for r in per_reading if name in r]
        if not values:
            continue
        # The winning value is the one the most readings agree on.
        best = max(set(values), key=values.count)
        result.fields[name] = FieldReading(
            value=best,
            readings_agreeing=values.count(best),
            readings_total=total_readings,
            exact=exact,
        )

    return result


def _min_agreement(readings: list[FieldReading]) -> float:
    return min((r.agreement for r in readings), default=0.0)


def verify_extracted_document(fields: InvoiceFields) -> list[Evidence]:
    """Turn extracted fields into evidence, tiered by how well they corroborate.

    The arithmetic is exact, so a mismatch is either real fraud or a misread.
    The two are indistinguishable from the arithmetic alone — only the reading
    agreement separates them. A mismatch is therefore allowed to FAIL (and so to
    drive an INVALID verdict) only when every number it depends on was
    corroborated. Otherwise the same finding is reported at REQUIRES_REVIEW,
    which surfaces it to the user without accusing the document.
    """
    checks: list[Evidence] = []
    checks.extend(_verify_statement_balance(fields))

    subtotal = fields.fields.get("subtotal")
    total = fields.fields.get("total")
    if subtotal is None or total is None:
        return checks

    tax = fields.fields.get("tax")
    discount = fields.fields.get("discount")

    computed = subtotal.value - (discount.value if discount else 0.0) + (tax.value if tax else 0.0)
    computed = round(computed, 2)
    difference = round(abs(computed - total.value), 2)
    consistent = difference <= _TOLERANCE

    involved = [f for f in (subtotal, total, tax, discount) if f is not None]
    corroborated = all(f.corroborated for f in involved)

    details: dict[str, object] = {
        "stated_total": total.value,
        "computed_total": computed,
        "subtotal": subtotal.value,
        "tax": tax.value if tax else 0.0,
        "discount": discount.value if discount else 0.0,
        "difference": difference,
        "agreement": round(_min_agreement(involved), 4),
        "corroborated": corroborated,
    }

    if not corroborated:
        # Symmetric with the mismatch case below: without a trustworthy reading
        # neither "these add up" nor "these don't" is a claim this can support.
        checks.append(Evidence(
            check="invoice_totals_consistency",
            category=CheckCategory.ARITHMETIC_VERIFICATION,
            status=CheckStatus.REQUIRES_REVIEW,
            confidence=0.5,
            severity=Severity.LOW if consistent else Severity.MEDIUM,
            message=(
                (
                    f"The figures read from this document do add up (stated {total.value}), "
                    f"but the reading was not reliable enough to confirm it."
                )
                if consistent else
                (
                    f"The figures read from this document do not add up (stated {total.value}, "
                    f"computed {computed}), but the reading was not reliable enough to be sure "
                    f"they were read correctly."
                )
            ) + " Manual review needed.",
            details=details,
        ))
    elif consistent:
        checks.append(Evidence(
            check="invoice_totals_consistency",
            category=CheckCategory.ARITHMETIC_VERIFICATION,
            status=CheckStatus.PASSED,
            confidence=1.0,
            severity=Severity.NONE,
            message=f"Stated total ({total.value}) matches subtotal, tax and discount.",
            details=details,
        ))
    else:
        checks.append(Evidence(
            check="invoice_totals_consistency",
            category=CheckCategory.ARITHMETIC_VERIFICATION,
            status=CheckStatus.FAILED,
            confidence=1.0,
            severity=Severity.CRITICAL,
            message=(
                f"Stated total {total.value} does not match the document's own figures "
                f"(subtotal {subtotal.value} - discount {details['discount']} "
                f"+ tax {details['tax']} = {computed}; off by {difference})."
            ),
            details=details,
        ))
    return checks


def _verify_statement_balance(fields: InvoiceFields) -> list[Evidence]:
    """Bank-statement branch: opening + credits - debits should equal closing.

    The arithmetic itself is `financial.verify_bank_balance`; this wrapper only
    decides whether the reading was good enough to let its verdict stand.
    """
    opening = fields.fields.get("opening")
    closing = fields.fields.get("closing")
    if opening is None or closing is None:
        return []

    credits = fields.fields.get("credits")
    debits = fields.fields.get("debits")

    evidence = verify_bank_balance(
        opening=opening.value,
        credits=credits.value if credits else 0.0,
        debits=debits.value if debits else 0.0,
        closing=closing.value,
        tolerance=_TOLERANCE,
    )

    involved = [f for f in (opening, closing, credits, debits) if f is not None]
    corroborated = all(f.corroborated for f in involved)
    evidence.details["agreement"] = round(_min_agreement(involved), 4)
    evidence.details["corroborated"] = corroborated

    # Same rule as the invoice branch, in both directions: an unreliable reading
    # may neither accuse the statement nor clear it.
    if not corroborated:
        reconciled = evidence.status == CheckStatus.PASSED
        evidence.status = CheckStatus.REQUIRES_REVIEW
        evidence.severity = Severity.LOW if reconciled else Severity.MEDIUM
        evidence.confidence = 0.5
        evidence.message = (
            (
                f"The balances read from this statement do reconcile "
                f"(closing {closing.value}), but the reading was not reliable "
                f"enough to confirm it."
            )
            if reconciled else
            (
                f"The balances read from this statement do not reconcile "
                f"(stated closing {closing.value}, computed "
                f"{evidence.details['computed_closing']}), but the reading was not "
                f"reliable enough to be sure they were read correctly."
            )
        ) + " Manual review needed."

    return [evidence]


# A column is only treated as money when its header says so. Inferring it from
# the values instead would eventually pick a quantity or a line number and
# compute a confident, wrong subtotal — the precise failure this design forbids.
_AMOUNT_COLUMN_RE = re.compile(
    r"\b(?:amount|total|price|value|cost|charge|sum|line\s+total)\b", re.IGNORECASE
)


def _amount_column_index(header: list[str]) -> int | None:
    for index, cell in enumerate(header):
        if _AMOUNT_COLUMN_RE.search(cell or ""):
            return index
    return None


def verify_line_items(
    tables: list[list[list[str]]],
    *,
    stated_subtotal: float | None,
) -> list[Evidence]:
    """Check that an invoice's line items sum to the subtotal it claims.

    Returns no evidence at all when the table cannot be read unambiguously.
    Silence is the correct output there: a guessed amount column produces a
    confident accusation against a document nobody actually checked.
    """
    if stated_subtotal is None:
        return []

    for table in tables:
        if len(table) < 2:
            continue
        column = _amount_column_index(table[0])
        if column is None:
            continue

        amounts: list[dict[str, float]] = []
        for row in table[1:]:
            if column >= len(row):
                continue
            value = _parse_amount(row[column])
            if value is not None:
                amounts.append({"amount": value})

        if not amounts:
            continue

        # financial.verify_invoice_totals owns the arithmetic; this module only
        # decides whether the inputs are trustworthy enough to hand it.
        results = verify_invoice_totals(amounts, expected_subtotal=stated_subtotal)
        subtotal_checks = [r for r in results if r.check == "invoice_subtotal"]
        for check in subtotal_checks:
            check.check = "invoice_line_items"
            check.details["computed_subtotal"] = check.details.pop("computed", None)
            check.details["stated_subtotal"] = check.details.pop("stated", None)
            check.details["line_item_count"] = len(amounts)
        return subtotal_checks

    return []
