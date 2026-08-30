"""Risk assessment and evidence aggregation engine."""

from __future__ import annotations

from app.models import (
    CheckStatus,
    Evidence,
    OverallStatus,
    RiskAssessment,
    Severity,
)

_SEVERITY_POINTS: dict[Severity, float] = {
    Severity.NONE: 0.0,
    Severity.LOW: 8.0,
    Severity.MEDIUM: 20.0,
    Severity.HIGH: 45.0,
    Severity.CRITICAL: 100.0,
}

# How much of a check's severity a given outcome actually realises. A warning is
# a partial signal, a review request weaker still; a pass contributes nothing.
_STATUS_MULTIPLIER: dict[CheckStatus, float] = {
    CheckStatus.FAILED: 1.0,
    CheckStatus.WARNING: 0.35,
    CheckStatus.REQUIRES_REVIEW: 0.25,
}

# Statuses that represent an actual determination. Everything else (unavailable,
# not applicable, unknown) means the check could not speak, which is a statement
# about confidence, never about risk.
_DETERMINATE: frozenset[CheckStatus] = frozenset({
    CheckStatus.PASSED,
    CheckStatus.FAILED,
    CheckStatus.WARNING,
    CheckStatus.REQUIRES_REVIEW,
})

# A failed critical check means the value is impossible, not merely suspicious —
# a Luhn checksum cannot "somewhat" fail. Other checks may not drag it down.
_CRITICAL_FAILURE_FLOOR = 90


def aggregate_evidence(checks: list[Evidence]) -> RiskAssessment:
    """Compute risk score and confidence from a list of evidence checks.

    Risk is an absolute sum of severity points, capped at 100 — not a ratio.
    The previous ratio form (accumulated / total_weight) divided out to 100 for
    any single failure, because only failing checks are ever assigned a
    severity: the denominator was built from the same set as the numerator, so
    a LOW warning and a CRITICAL checksum failure scored identically.

    Confidence is evidence coverage: what fraction of the attempted checks
    actually returned a determination, weighted by how sure each one was. A
    check that could not run lowers confidence and leaves risk untouched, so
    missing evidence can no longer read as safety.
    """
    total = len(checks)
    if total == 0:
        return RiskAssessment(
            risk_score=0,
            confidence=0,
            level="unknown",
            checks_determinate=0,
            checks_total=0,
        )

    accumulated = 0.0
    has_critical_failure = False
    determinate: list[Evidence] = []

    for check in checks:
        if check.status in _DETERMINATE:
            determinate.append(check)
        multiplier = _STATUS_MULTIPLIER.get(check.status)
        if multiplier is None:
            continue
        accumulated += _SEVERITY_POINTS.get(check.severity, 0.0) * multiplier
        if check.status == CheckStatus.FAILED and check.severity == Severity.CRITICAL:
            has_critical_failure = True

    risk_score = min(100, int(round(accumulated)))
    if has_critical_failure:
        risk_score = max(risk_score, _CRITICAL_FAILURE_FLOOR)

    # Each check reports how sure it is of its own result; that was previously
    # collected and discarded.
    if determinate:
        mean_check_confidence = sum(c.confidence for c in determinate) / len(determinate)
    else:
        mean_check_confidence = 0.0
    coverage = len(determinate) / total
    confidence = int(round(coverage * mean_check_confidence * 100))
    confidence = min(100, max(0, confidence))

    if not determinate:
        level = "unknown"
    elif risk_score >= 70:
        level = "high"
    elif risk_score >= 40:
        level = "elevated"
    elif risk_score >= 15:
        level = "moderate"
    else:
        level = "low"

    return RiskAssessment(
        risk_score=risk_score,
        confidence=confidence,
        level=level,
        checks_determinate=len(determinate),
        checks_total=total,
    )


def determine_overall_status(
    risk: RiskAssessment,
    checks: list[Evidence],
    limitations: list[str],
) -> OverallStatus:
    """Derive overall status from risk assessment and evidence."""
    failed = [c for c in checks if c.status == CheckStatus.FAILED]
    warnings = [c for c in checks if c.status == CheckStatus.WARNING]
    reviews = [c for c in checks if c.status == CheckStatus.REQUIRES_REVIEW]
    # Reuses the same set aggregate_evidence scores against, rather than the
    # narrower `status == UNAVAILABLE` test this used to apply.
    #
    # That test was the bug. CheckStatus has three non-determinate values —
    # UNAVAILABLE, NOT_APPLICABLE and UNKNOWN — and only the first was treated
    # as "this check could not speak". So a run whose every check came back
    # NOT_APPLICABLE had no failures, no warnings and no reviews, fell straight
    # through to the bottom of the first branch, and returned LIKELY_VALID.
    #
    # Concretely: typing sixteen 1s classified as a generic identifier, for
    # which the single available check does not apply. Zero checks determined
    # anything and the API answered "likely valid" — the exact failure mode
    # aggregate_evidence's docstring promises against, that missing evidence
    # must never read as safety. A fraud tool asserting validity on no evidence
    # is worse than one that declines to answer.
    determinate = [c for c in checks if c.status in _DETERMINATE]

    if len(checks) == 0:
        return OverallStatus.INSUFFICIENT_EVIDENCE

    # Nothing actually ran. There is no verdict to give, only an absence.
    if not determinate:
        return OverallStatus.INSUFFICIENT_EVIDENCE

    if not failed and not warnings and not reviews:
        return OverallStatus.LIKELY_VALID

    if failed:
        has_critical = any(c.severity == Severity.CRITICAL for c in failed)
        if has_critical or risk.risk_score >= 70:
            return OverallStatus.INVALID
        if risk.risk_score >= 40:
            return OverallStatus.REQUIRES_REVIEW
        return OverallStatus.VALID_WITH_WARNINGS

    if warnings:
        return OverallStatus.VALID_WITH_WARNINGS

    if reviews:
        return OverallStatus.REQUIRES_REVIEW

    return OverallStatus.INSUFFICIENT_EVIDENCE
