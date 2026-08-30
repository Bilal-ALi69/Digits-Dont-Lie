"""CNIC (Pakistani National Identity Card) validation.

The defining fact about a CNIC is what it does *not* have: a check digit. A card
number carries Luhn, a passport MRZ carries the ICAO 9303 composite, and both
let this system arrive at a conclusion by arithmetic alone. A CNIC carries
neither. NADRA assigns the thirteen digits from its own registry and publishes
no formula that a third party can recompute.

That shapes the whole engine. Everything here can prove a number *malformed* —
wrong length, an unissued region code, a placeholder run of digits — and none of
it can prove a number was issued. A well-formed CNIC therefore leaves this
engine as REQUIRES_REVIEW, never as a pass, because the only thing that could
turn "well-formed" into "genuine" is a NADRA lookup this system does not have.
Reporting anything stronger would be fabricated confidence about a real
person's identity document.
"""

from __future__ import annotations

import re

from app.models import CheckCategory, CheckStatus, Evidence, Severity

# A CNIC is exactly thirteen digits, printed grouped 5-7-1.
CNIC_LENGTH = 13
_AREA_LENGTH = 5
_SERIAL_LENGTH = 7

# First digit: the province or territory that issued the number. NADRA assigns
# 1-7; 0, 8 and 9 are not issued, so a number starting with one of those cannot
# have come from the registry.
_REGIONS: dict[str, str] = {
    "1": "Khyber Pakhtunkhwa",
    "2": "FATA",
    "3": "Punjab",
    "4": "Sindh",
    "5": "Balochistan",
    "6": "Islamabad",
    "7": "Gilgit-Baltistan",
}

# Hyphens and spaces are how a CNIC is printed, not corruption in the input.
_SEPARATORS_RE = re.compile(r"[\s\-‐-―]")


def normalize_cnic(value: str) -> str:
    """Strip the printed separators, leaving whatever characters remain.

    Deliberately does not drop non-digits: format_check needs to see that
    letters were present in order to report them, and silently deleting them
    would turn a corrupt read into a plausible-looking number.
    """
    return _SEPARATORS_RE.sub("", value.strip())


def _is_well_formed(normalized: str) -> bool:
    """True when the number could be a CNIC: right length, right region code."""
    return (
        len(normalized) == CNIC_LENGTH
        and normalized.isdigit()
        and normalized[0] in _REGIONS
    )


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def format_check(value: str) -> Evidence:
    """Length and numeric composition, tolerant of the printed 5-7-1 grouping."""
    normalized = normalize_cnic(value)

    if not normalized:
        return Evidence(
            check="cnic_format",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.NOT_APPLICABLE,
            confidence=1.0,
            message="No value was supplied to check.",
        )

    if not normalized.isdigit():
        return Evidence(
            check="cnic_format",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.FAILED,
            confidence=1.0,
            severity=Severity.CRITICAL,
            message="A CNIC is digits only; this value contains other characters.",
            details={"normalized_length": len(normalized)},
        )

    if len(normalized) != CNIC_LENGTH:
        return Evidence(
            check="cnic_format",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.FAILED,
            confidence=1.0,
            severity=Severity.CRITICAL,
            message=(
                f"A CNIC is {CNIC_LENGTH} digits; this value has {len(normalized)}."
            ),
            details={"digits": len(normalized), "expected": CNIC_LENGTH},
        )

    return Evidence(
        check="cnic_format",
        category=CheckCategory.FORMAT_VALIDATION,
        status=CheckStatus.PASSED,
        confidence=1.0,
        message=f"{CNIC_LENGTH} digits, matching the CNIC format.",
        details={"digits": CNIC_LENGTH, "formatted": format_cnic(normalized)},
    )


def province_check(value: str) -> Evidence:
    """The leading digit names the issuing province or territory."""
    normalized = normalize_cnic(value)

    if len(normalized) != CNIC_LENGTH or not normalized.isdigit():
        return Evidence(
            check="cnic_region_code",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.NOT_APPLICABLE,
            confidence=1.0,
            message="The region code can only be read from a well-formed CNIC.",
        )

    code = normalized[0]
    region = _REGIONS.get(code)
    if region is None:
        return Evidence(
            check="cnic_region_code",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.FAILED,
            confidence=1.0,
            severity=Severity.CRITICAL,
            message=(
                f"Leading digit {code} is not an issued region code; "
                "NADRA assigns 1-7."
            ),
            details={"region_code": code},
        )

    return Evidence(
        check="cnic_region_code",
        category=CheckCategory.FORMAT_VALIDATION,
        status=CheckStatus.PASSED,
        confidence=1.0,
        message=f"Region code {code} corresponds to {region}.",
        details={"region_code": code, "region": region},
    )


def gender_digit_check(value: str) -> Evidence:
    """The final digit encodes gender: odd male, even female.

    Descriptive only. Every value of the digit is legitimate, so this check
    reports what the number says about itself and carries no severity — there
    is no reading of the final digit that makes a CNIC wrong.
    """
    normalized = normalize_cnic(value)

    if len(normalized) != CNIC_LENGTH or not normalized.isdigit():
        return Evidence(
            check="cnic_gender_digit",
            category=CheckCategory.SEMANTIC_ANALYSIS,
            status=CheckStatus.NOT_APPLICABLE,
            confidence=1.0,
            message="The gender digit can only be read from a well-formed CNIC.",
        )

    digit = int(normalized[-1])
    gender = "male" if digit % 2 else "female"
    return Evidence(
        check="cnic_gender_digit",
        category=CheckCategory.SEMANTIC_ANALYSIS,
        status=CheckStatus.PASSED,
        confidence=1.0,
        severity=Severity.NONE,
        message=f"Final digit {digit} is {'odd' if digit % 2 else 'even'}, indicating {gender}.",
        details={"gender_digit": digit, "gender": gender},
    )


def degenerate_check(value: str) -> Evidence:
    """Reject placeholder runs that satisfy every structural rule.

    With no checksum to fail, a made-up number like 1111111111111 clears length
    and region on its own. These sequences are what mockups, form placeholders
    and fabricated documents actually contain, so without this check the engine
    would have nothing to say against them.
    """
    normalized = normalize_cnic(value)

    if not normalized or not normalized.isdigit():
        return Evidence(
            check="cnic_degenerate_sequence",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.NOT_APPLICABLE,
            confidence=1.0,
            message="Input is not numeric.",
        )

    if len(set(normalized)) == 1:
        return Evidence(
            check="cnic_degenerate_sequence",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.FAILED,
            confidence=1.0,
            severity=Severity.CRITICAL,
            message=(
                f"Every digit is {normalized[0]}; a placeholder, not an issued CNIC."
            ),
            details={"pattern": "repeated_digit"},
        )

    # Counted modulo ten so a run that rolls over (…7890123…) is caught too;
    # a plain difference would break at the 9 and let the sequence through.
    pairs = list(zip(normalized, normalized[1:]))
    ascending = all((int(b) - int(a)) % 10 == 1 for a, b in pairs)
    descending = all((int(a) - int(b)) % 10 == 1 for a, b in pairs)
    if ascending or descending:
        return Evidence(
            check="cnic_degenerate_sequence",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.FAILED,
            confidence=1.0,
            severity=Severity.CRITICAL,
            message="Digits run in strict sequence; a placeholder, not an issued CNIC.",
            details={"pattern": "ascending" if ascending else "descending"},
        )

    return Evidence(
        check="cnic_degenerate_sequence",
        category=CheckCategory.FORMAT_VALIDATION,
        status=CheckStatus.PASSED,
        confidence=1.0,
        message="Digits show no placeholder pattern.",
    )


def authority_verification_note(value: str) -> Evidence:
    """The honesty ceiling, stated as evidence rather than left implicit.

    Emitted as REQUIRES_REVIEW so it reaches the risk engine as an open
    question. Without it a well-formed CNIC would clear every check that ran
    and be reported as likely valid — the system asserting a person's identity
    document is genuine on the strength of its digit count.
    """
    normalized = normalize_cnic(value)

    if not _is_well_formed(normalized):
        return Evidence(
            check="cnic_authority_verification",
            category=CheckCategory.EXTERNAL_VERIFICATION,
            status=CheckStatus.NOT_APPLICABLE,
            confidence=1.0,
            message=(
                "The number is already malformed, which is conclusive without "
                "an authority lookup."
            ),
        )

    return Evidence(
        check="cnic_authority_verification",
        category=CheckCategory.EXTERNAL_VERIFICATION,
        status=CheckStatus.REQUIRES_REVIEW,
        confidence=1.0,
        severity=Severity.NONE,
        message=(
            "A CNIC carries no check digit, so a well-formed number cannot be "
            "confirmed as issued by arithmetic. Only a NADRA record check can "
            "establish that this number belongs to a real cardholder."
        ),
        details={"authority": "NADRA", "checksum_available": False},
    )


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------

def format_cnic(value: str) -> str:
    """Render as the printed 5-7-1 grouping, or return the input untouched."""
    normalized = normalize_cnic(value)
    if len(normalized) != CNIC_LENGTH or not normalized.isdigit():
        return value
    area = normalized[:_AREA_LENGTH]
    serial = normalized[_AREA_LENGTH:_AREA_LENGTH + _SERIAL_LENGTH]
    return f"{area}-{serial}-{normalized[-1]}"


def mask_cnic(value: str) -> str:
    """Hide the family/serial block, which is the part that identifies a person.

    The area code and gender digit are kept because they are what the checks
    above actually reason about — a masked value the reviewer cannot connect to
    the findings is no use to them.
    """
    normalized = normalize_cnic(value)
    if len(normalized) != CNIC_LENGTH or not normalized.isdigit():
        return "*" * len(normalized)
    area = normalized[:_AREA_LENGTH]
    return f"{area}-{'*' * _SERIAL_LENGTH}-{normalized[-1]}"
