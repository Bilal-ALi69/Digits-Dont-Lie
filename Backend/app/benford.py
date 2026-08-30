"""
Benford's Law calculation engine.

Implements the core statistics for a Benford goodness-of-fit test:

  * Expected frequency  P(d) = log10(1 + 1/d)
  * Observed counts / frequencies for leading digits 1..9
  * Chi-Square statistic comparing observed vs expected counts
  * P-value approximation
  * First-two-digit analysis
  * Applicability assessment
"""

import math
from collections import Counter
from collections.abc import Sequence
from typing import NotRequired, TypedDict

from app.preprocess import first_leading_digit, first_two_leading_digits

LEADING_DIGITS = list(range(1, 10))
TWO_DIGIT_RANGE = list(range(10, 100))


class BenfordResult(TypedDict):
    total_count: int
    invalid_count: int
    observed_counts: dict[str, int]
    observed_frequencies: dict[str, float]
    expected_frequencies: dict[str, float]
    chi_square: float
    p_value: NotRequired[float | None]
    sample_size_appropriate: NotRequired[bool]
    applicability: NotRequired[str]


class TwoDigitBenfordResult(TypedDict):
    total_count: int
    invalid_count: int
    observed_counts: dict[str, int]
    observed_frequencies: dict[str, float]
    expected_frequencies: dict[str, float]
    chi_square: float
    p_value: NotRequired[float | None]
    applicability: NotRequired[str]


def expected_frequency(digit: int) -> float:
    """P(d) = log10(1 + 1/d)"""
    return math.log10(1.0 + 1.0 / digit)


def _regularized_lower_incomplete_gamma(a: float, x: float) -> float:
    """Compute P(a, x) = γ(a,x) / Γ(a), the regularized lower incomplete gamma.

    Uses a series expansion for x < a + 1, and a continued fraction otherwise.
    Both converge rapidly for the chi-square ranges we encounter (dof=8 or 89).
    """
    if x <= 0.0:
        return 0.0

    if x < a + 1.0:
        # Series expansion
        ap = a
        term = 1.0 / a
        total = term
        for _ in range(300):
            ap += 1.0
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-15:
                break
        return total * math.exp(-x + a * math.log(x) - math.lgamma(a))
    else:
        # Continued fraction (Lentz's method)
        b = x + 1.0 - a
        c = 1e30
        d = 1.0 / b
        h = d
        for i in range(1, 300):
            an = -i * (i - a)
            b += 2.0
            d = an * d + b
            if abs(d) < 1e-30:
                d = 1e-30
            c = b + an / c
            if abs(c) < 1e-30:
                c = 1e-30
            d = 1.0 / d
            delta = d * c
            h *= delta
            if abs(delta - 1.0) < 1e-15:
                break
        return 1.0 - math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def _chi_square_p_value(chi_sq: float, dof: int) -> float | None:
    """Compute the survival-function p-value P(X > chi_sq) for chi-square with *dof* degrees of freedom."""
    if dof <= 0 or chi_sq < 0:
        return None
    if chi_sq == 0:
        return 1.0
    try:
        p = 1.0 - _regularized_lower_incomplete_gamma(dof / 2.0, chi_sq / 2.0)
        return min(max(p, 0.0), 1.0)
    except (ValueError, OverflowError, ZeroDivisionError):
        return None


def _assess_applicability(total_count: int, numbers: Sequence[float]) -> str:
    """Determine whether Benford's Law is appropriate for this dataset."""
    if total_count < 50:
        return "insufficient_data"
    if total_count < 100:
        return "questionable"
    return "applicable"


def analyze(numbers: Sequence[float]) -> BenfordResult:
    """Run the full Benford analysis over a cleaned list of numbers."""
    digits: list[int] = []
    invalid_count = 0
    for value in numbers:
        digit = first_leading_digit(value)
        if digit is None:
            invalid_count += 1
        else:
            digits.append(digit)

    n = len(digits)

    counts = Counter(digits)
    observed_counts = {str(d): counts[d] for d in LEADING_DIGITS}
    observed_freqs: dict[str, float] = {
        str(d): (observed_counts[str(d)] / n * 100.0) if n else 0.0
        for d in LEADING_DIGITS
    }
    expected_freqs: dict[str, float] = {
        str(d): expected_frequency(d) * 100.0 for d in LEADING_DIGITS
    }

    chi_square = 0.0
    if n:
        for d in LEADING_DIGITS:
            expected_count = n * expected_frequency(d)
            diff = observed_counts[str(d)] - expected_count
            chi_square += (diff * diff) / expected_count

    p_value = _chi_square_p_value(chi_square, 8)
    applicability = _assess_applicability(n, numbers)

    return BenfordResult(
        total_count=n,
        invalid_count=invalid_count,
        observed_counts=observed_counts,
        observed_frequencies=observed_freqs,
        expected_frequencies=expected_freqs,
        chi_square=round(chi_square, 6),
        p_value=p_value,
        sample_size_appropriate=n >= 50,
        applicability=applicability,
    )


def first_two_digit_expected_frequency(digit: int) -> float:
    """P(d) = log10(1 + 1/d) for two-digit numbers 10..99."""
    return math.log10(1.0 + 1.0 / digit)


def analyze_two_digit(numbers: Sequence[float]) -> TwoDigitBenfordResult:
    """Run first-two-digit Benford analysis (digits 10-99)."""
    digits: list[int] = []
    invalid_count = 0
    for value in numbers:
        digit = first_two_leading_digits(value)
        if digit is None:
            invalid_count += 1
        else:
            digits.append(digit)

    n = len(digits)

    counts = Counter(digits)
    observed_counts = {str(d): counts[d] for d in TWO_DIGIT_RANGE}
    observed_freqs: dict[str, float] = {
        str(d): (observed_counts[str(d)] / n * 100.0) if n else 0.0
        for d in TWO_DIGIT_RANGE
    }
    expected_freqs: dict[str, float] = {
        str(d): first_two_digit_expected_frequency(d) * 100.0 for d in TWO_DIGIT_RANGE
    }

    chi_square = 0.0
    if n:
        for d in TWO_DIGIT_RANGE:
            expected_count = n * first_two_digit_expected_frequency(d)
            diff = observed_counts[str(d)] - expected_count
            chi_square += (diff * diff) / expected_count

    p_value = _chi_square_p_value(chi_square, 89)
    applicability = _assess_applicability(n, numbers)

    return TwoDigitBenfordResult(
        total_count=n,
        invalid_count=invalid_count,
        observed_counts=observed_counts,
        observed_frequencies=observed_freqs,
        expected_frequencies=expected_freqs,
        chi_square=round(chi_square, 6),
        p_value=p_value,
        applicability=applicability,
    )
