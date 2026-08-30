"""Card number validation: Luhn algorithm, network detection, format checks."""

from __future__ import annotations

import re

from app.models import CheckCategory, CheckStatus, Evidence, Severity


def _digits_only(card: str) -> str:
    return re.sub(r"[^0-9]", "", card)


# ---------------------------------------------------------------------------
# Raw helpers (return plain bool / str, not Evidence)
# Used by app.ocr and app.engines.classifier to avoid duplicating logic.
# ---------------------------------------------------------------------------

def luhn_valid(card_number: str) -> bool:
    """Return True if *card_number* passes the Luhn checksum."""
    digits = _digits_only(card_number)
    if not digits.isdigit() or len(digits) < 13:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def card_network(card_number: str) -> str | None:
    """Return the card network name (e.g. 'visa') or None if not recognized."""
    digits = _digits_only(card_number)
    for name, pattern, lengths, _prefix in _NETWORK_RULES:
        if len(digits) in lengths and pattern.match(digits):
            return name
    return None


def luhn_check(card_number: str) -> Evidence:
    digits = _digits_only(card_number)
    if not digits or not digits.isdigit():
        return Evidence(
            check="luhn_checksum",
            category=CheckCategory.MATHEMATICAL_VALIDATION,
            status=CheckStatus.NOT_APPLICABLE,
            confidence=1.0,
            message="Input is not numeric.",
        )

    if len(digits) < 13 or len(digits) > 19:
        return Evidence(
            check="luhn_checksum",
            category=CheckCategory.MATHEMATICAL_VALIDATION,
            status=CheckStatus.WARNING,
            confidence=0.9,
            severity=Severity.LOW,
            message=f"Unusual length ({len(digits)} digits); typical cards are 13-19 digits.",
        )

    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d

    passed = total % 10 == 0
    return Evidence(
        check="luhn_checksum",
        category=CheckCategory.MATHEMATICAL_VALIDATION,
        status=CheckStatus.PASSED if passed else CheckStatus.FAILED,
        confidence=1.0,
        severity=Severity.NONE if passed else Severity.CRITICAL,
        message=(
            "The supplied number satisfies the Luhn checksum."
            if passed
            else "The supplied number fails the Luhn checksum."
        ),
        details={"valid": passed, "sum": total},
    )


_NETWORK_RULES: list[tuple[str, re.Pattern[str], tuple[int, ...], int | None]] = [
    ("visa", re.compile(r"^4[0-9]{12}(?:[0-9]{3})?(?:[0-9]{3})?$"), (13, 16, 19), None),
    ("mastercard", re.compile(r"^5[1-5][0-9]{14}$"), (16,), None),
    ("mastercard", re.compile(r"^2[2-7][0-9]{14}$"), (16,), None),
    ("amex", re.compile(r"^3[47][0-9]{13}$"), (15,), None),
    ("discover", re.compile(r"^6(?:011|5[0-9]{2})[0-9]{12}$"), (16,), None),
    ("diners", re.compile(r"^3(?:0[0-5]|[68][0-9])[0-9]{11,13}$"), (14, 16), None),
    ("jcb", re.compile(r"^(?:2131|1800|35\d{3})\d{11,15}$"), (15, 16, 17, 18, 19), None),
    ("unionpay", re.compile(r"^62[0-9]{14,17}$"), (16, 17, 18, 19), None),
    ("maestro", re.compile(r"^(?:5018|5020|5038|5893|6304|6759|676[1-3])\d{8,15}$"), (12, 13, 14, 15, 16, 17, 18, 19), None),
]


def degenerate_check(card_number: str) -> Evidence:
    """Reject placeholder sequences that satisfy Luhn without being card numbers.

    Luhn is a transcription-error check, not a proof of issuance, and some
    degenerate strings pass it outright: all-zeros sums to zero, and zero is
    divisible by ten. Mockups and form placeholders use exactly these, so
    without this check "0000 0000 0000 0000" reports as a likely-valid card.
    """
    digits = _digits_only(card_number)
    if not digits or not digits.isdigit():
        return Evidence(
            check="degenerate_sequence",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.NOT_APPLICABLE,
            confidence=1.0,
            message="Input is not numeric.",
        )

    if len(set(digits)) == 1:
        return Evidence(
            check="degenerate_sequence",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.FAILED,
            confidence=1.0,
            severity=Severity.CRITICAL,
            message=f"Every digit is {digits[0]}; a placeholder, not an issued card number.",
            details={"pattern": "repeated_digit"},
        )

    ascending = all(int(b) - int(a) == 1 for a, b in zip(digits, digits[1:]))
    descending = all(int(a) - int(b) == 1 for a, b in zip(digits, digits[1:]))
    if ascending or descending:
        return Evidence(
            check="degenerate_sequence",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.FAILED,
            confidence=1.0,
            severity=Severity.CRITICAL,
            message="Digits run in strict sequence; a placeholder, not an issued card number.",
            details={"pattern": "ascending" if ascending else "descending"},
        )

    return Evidence(
        check="degenerate_sequence",
        category=CheckCategory.FORMAT_VALIDATION,
        status=CheckStatus.PASSED,
        confidence=1.0,
        message="Digits show no placeholder pattern.",
    )


# Card numbers the networks and processors publish as test values. Every one of
# these is documented public sample data that cannot be charged — they exist so
# integrations can be exercised without a real card, which is exactly why they
# turn up in screenshots, tutorials and fraudulent form submissions alike.
#
# They are not degenerate: 4111 1111 1111 1111 has mixed digits, satisfies Luhn,
# and matches Visa's numbering rules, so every structural check this engine runs
# passes it. Reporting the most famous test number in the world as "likely
# valid" is technically defensible and practically useless — it is the one
# sixteen-digit string a reviewer is most likely to try.
_TEST_CARD_NUMBERS: frozenset[str] = frozenset({
    # Visa
    "4111111111111111", "4012888888881881", "4222222222222",
    "4242424242424242", "4000056655665556", "4000000000000002",
    # Mastercard
    "5555555555554444", "5105105105105100", "5200828282828210",
    "2223003122003222", "5555555555554477",
    # American Express
    "378282246310005", "371449635398431", "378734493671000",
    # Discover
    "6011111111111117", "6011000990139424", "6011981111111113",
    # JCB
    "3530111333300000", "3566002020360505",
    # Diners Club
    "30569309025904", "38520000023237", "36227206271667",
    # UnionPay
    "6200000000000005",
})


def published_test_card_check(card_number: str) -> Evidence:
    """Flag publicly published test card numbers.

    A WARNING rather than a FAILED: a test number is not evidence of fraud, and
    calling it fraud would be its own kind of wrong. It is evidence that no
    conclusion about a real card can be drawn — which downstream becomes
    "valid with warnings", and reaches the user as insufficient evidence rather
    than as an assurance.
    """
    digits = _digits_only(card_number)
    if not digits:
        return Evidence(
            check="test_card_number",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.NOT_APPLICABLE,
            confidence=1.0,
            message="No digits to compare against known test numbers.",
        )

    if digits in _TEST_CARD_NUMBERS:
        return Evidence(
            check="test_card_number",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.WARNING,
            confidence=1.0,
            severity=Severity.MEDIUM,
            message=(
                "This is a publicly published test card number. It satisfies "
                "every structural check by design and does not correspond to an "
                "issued card, so validity cannot be inferred from it."
            ),
            details={"pattern": "known_test_number"},
        )

    return Evidence(
        check="test_card_number",
        category=CheckCategory.FORMAT_VALIDATION,
        status=CheckStatus.PASSED,
        confidence=1.0,
        message="Not a published test card number.",
    )


def detect_network(card_number: str) -> Evidence:
    digits = _digits_only(card_number)
    for name, pattern, lengths, _prefix in _NETWORK_RULES:
        if len(digits) in lengths and pattern.match(digits):
            return Evidence(
                check="network_detection",
                category=CheckCategory.FORMAT_VALIDATION,
                status=CheckStatus.PASSED,
                confidence=0.95,
                message=f"Number matches {name} numbering rules.",
                details={"network": name},
            )

    return Evidence(
        check="network_detection",
        category=CheckCategory.FORMAT_VALIDATION,
        status=CheckStatus.UNKNOWN,
        confidence=0.5,
        message="Number does not match any known card network format.",
    )


def format_check(card_number: str) -> list[Evidence]:
    digits = _digits_only(card_number)
    results: list[Evidence] = []

    has_separators = card_number != digits
    if has_separators:
        results.append(Evidence(
            check="format_separators",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.PASSED,
            confidence=1.0,
            message="Separators (spaces/hyphens) removed for validation.",
        ))

    if not digits.isdigit():
        results.append(Evidence(
            check="format_numeric",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.FAILED,
            confidence=1.0,
            severity=Severity.HIGH,
            message="Card number contains non-numeric characters.",
        ))
        return results

    if len(digits) < 13:
        results.append(Evidence(
            check="format_length",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.FAILED,
            confidence=1.0,
            severity=Severity.HIGH,
            message=f"Too short: {len(digits)} digits (minimum 13).",
        ))
    elif len(digits) > 19:
        results.append(Evidence(
            check="format_length",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.FAILED,
            confidence=1.0,
            severity=Severity.HIGH,
            message=f"Too long: {len(digits)} digits (maximum 19).",
        ))
    else:
        results.append(Evidence(
            check="format_length",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.PASSED,
            confidence=1.0,
            message=f"Length {len(digits)} digits is within expected range.",
        ))

    return results


def mask_card_number(card_number: str) -> str:
    digits = _digits_only(card_number)
    if len(digits) < 4:
        return "*" * len(digits)
    return f"**** **** **** {digits[-4:]}"
