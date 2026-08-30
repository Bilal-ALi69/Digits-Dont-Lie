"""Financial arithmetic verification engine."""

from __future__ import annotations

from app.models import CheckCategory, CheckStatus, Evidence, Severity


def verify_invoice_totals(
    line_items: list[dict[str, float]],
    expected_subtotal: float | None = None,
    discount: float = 0.0,
    tax_rate: float = 0.0,
    expected_total: float | None = None,
    tolerance: float = 0.02,
) -> list[Evidence]:
    """Verify arithmetic consistency of an invoice."""
    results: list[Evidence] = []
    unparseable_count = 0

    def _safe_float(val: object) -> float:
        nonlocal unparseable_count
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val.replace(",", "").replace("$", "").replace("€", "").replace("£", "").replace("₹", ""))
            except ValueError:
                unparseable_count += 1
                return 0.0
        unparseable_count += 1
        return 0.0

    computed_subtotal = sum(_safe_float(item.get("amount", 0.0)) for item in line_items)
    computed_subtotal = round(computed_subtotal, 2)

    # A line item whose amount couldn't be parsed is silently treated as 0 in the
    # sum above, which would let manipulated/malformed line items pass arithmetic
    # verification undetected. Surface it explicitly instead of failing silently.
    if unparseable_count:
        results.append(Evidence(
            check="invoice_line_item_parsing",
            category=CheckCategory.ARITHMETIC_VERIFICATION,
            status=CheckStatus.WARNING,
            confidence=1.0,
            severity=Severity.MEDIUM,
            message=(
                f"{unparseable_count} line item(s) had an unparseable or missing "
                f"amount and were treated as 0 in the subtotal/total calculation."
            ),
            details={"unparseable_count": unparseable_count},
        ))

    if expected_subtotal is not None:
        diff = abs(computed_subtotal - expected_subtotal)
        passed = diff <= tolerance
        results.append(Evidence(
            check="invoice_subtotal",
            category=CheckCategory.ARITHMETIC_VERIFICATION,
            status=CheckStatus.PASSED if passed else CheckStatus.FAILED,
            confidence=1.0,
            severity=Severity.NONE if passed else Severity.HIGH,
            message=(
                f"Subtotal matches ({expected_subtotal})."
                if passed
                else f"Subtotal mismatch: computed {computed_subtotal} vs stated {expected_subtotal} (diff: {diff})."
            ),
            details={
                "computed": computed_subtotal,
                "stated": expected_subtotal,
                "difference": round(diff, 2),
            },
        ))

    after_discount = computed_subtotal - discount
    computed_tax = round(after_discount * tax_rate, 2)
    computed_total = round(after_discount + computed_tax, 2)

    if expected_total is not None:
        diff = abs(computed_total - expected_total)
        passed = diff <= tolerance
        results.append(Evidence(
            check="invoice_total",
            category=CheckCategory.ARITHMETIC_VERIFICATION,
            status=CheckStatus.PASSED if passed else CheckStatus.FAILED,
            confidence=1.0,
            severity=Severity.NONE if passed else Severity.CRITICAL,
            message=(
                f"Total matches ({expected_total})."
                if passed
                else f"Total mismatch: computed {computed_total} vs stated {expected_total} (diff: {diff})."
            ),
            details={
                "computed": computed_total,
                "stated": expected_total,
                "difference": round(diff, 2),
                "subtotal": computed_subtotal,
                "discount": discount,
                "tax": computed_tax,
            },
        ))

    return results


def verify_bank_balance(
    opening: float,
    credits: float,
    debits: float,
    closing: float,
    tolerance: float = 0.02,
) -> Evidence:
    """Verify bank statement balance arithmetic."""
    expected_closing = round(opening + credits - debits, 2)
    diff = abs(expected_closing - closing)
    passed = diff <= tolerance

    return Evidence(
        check="bank_balance",
        category=CheckCategory.ARITHMETIC_VERIFICATION,
        status=CheckStatus.PASSED if passed else CheckStatus.FAILED,
        confidence=1.0,
        severity=Severity.NONE if passed else Severity.HIGH,
        message=(
            "Balance arithmetic is consistent (opening + credits - debits = closing)."
            if passed
            else f"Balance mismatch: expected {expected_closing}, stated {closing} (diff: {diff})."
        ),
        details={
            "opening": opening,
            "credits": credits,
            "debits": debits,
            "stated_closing": closing,
            "computed_closing": expected_closing,
            "difference": round(diff, 2),
        },
    )
