"""
Preprocessing utilities.

These functions turn raw input values (integers, floats) into the first
non-zero leading digit required by Benford's Law. Per Benford, only the
*leading* digit matters, so signs, decimal points and scale all get stripped.

Digit extraction uses Python's ``repr()`` for correct rounding at extreme
magnitudes (the old multiply/divide-by-10 loop accumulated floating-point
error below ~1e-240).
"""

import math
from typing import Optional


def _extract_leading_digits(value) -> Optional[str]:
    """Return the significant digits of *value* as a string, or None.

    Uses ``repr()`` so that Python's float formatting gives us the correctly
    rounded significant digits — no accumulated loop error at extreme scales.
    """
    try:
        num = abs(float(value))
    except (TypeError, ValueError):
        return None

    if not math.isfinite(num) or num == 0.0:
        return None

    # repr() gives us the shortest correctly-rounded decimal representation.
    # Strip the sign (already abs'd) and any leading/trailing junk.
    s = repr(num)

    # Pull out just the digit characters.  repr may give "1e-300" or "3.4e+50",
    # so we need to handle the exponent separately.
    mantissa, _, exponent = s.partition("e")
    digits_only = mantissa.replace(".", "").lstrip("0")

    if not digits_only:
        return None

    if exponent:
        # e.g. "1e-300" -> mantissa "1" with exponent -300.
        # The missing trailing digits in the mantissa are implicitly zero,
        # so pad with enough zeros to give us at least 2 significant digits.
        if len(digits_only) < 2:
            digits_only = digits_only + "0" * (2 - len(digits_only))
        return digits_only

    # No exponent: e.g. "3400.0" -> "34000" -> leading digit is "3"
    return digits_only


def first_leading_digit(value) -> Optional[int]:
    """
    Extract the first non-zero leading digit (1-9) from a numeric value.

    Behaviour:
      * Negative numbers are treated by absolute value (sign is irrelevant).
      * Decimals are handled: the first non-zero digit is taken even when the
        number is smaller than 1 (e.g. 0.045 -> 4).
      * The magnitude is ignored (e.g. 45, 4500 and 0.45 all yield 4).
      * Zero returns ``None`` because it has no leading digit and is rejected
        as invalid for Benford analysis.

    Parameters
    ----------
    value : int | float | str
        A single raw value. Strings are coerced via ``float()``.

    Returns
    -------
    Optional[int]
        The leading digit in 1..9, or ``None`` if the value is zero,
        non-finite (NaN/inf), or otherwise cannot be parsed.
    """
    digits = _extract_leading_digits(value)
    if digits and digits[0].isdigit() and digits[0] != "0":
        return int(digits[0])
    return None


def first_two_leading_digits(value) -> Optional[int]:
    """
    Extract the first two significant digits (10-99) from a numeric value.

    Parameters
    ----------
    value : int | float | str
        A single raw value.

    Returns
    -------
    Optional[int]
        Two-digit integer in 10..99, or ``None`` if zero / non-finite / unparseable.
    """
    digits = _extract_leading_digits(value)
    if not digits or len(digits) < 2:
        return None
    first_two = digits[:2]
    if first_two[0] == "0":
        return None
    result = int(first_two)
    if 10 <= result <= 99:
        return result
    return None
