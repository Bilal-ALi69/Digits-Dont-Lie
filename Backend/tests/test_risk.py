"""Tests for risk assessment and evidence aggregation."""

from app.engines.risk import aggregate_evidence, determine_overall_status
from app.models import (
    CheckStatus,
    Evidence,
    OverallStatus,
    Severity,
    CheckCategory,
    simplify_status,
)


def _make_check(status: CheckStatus, severity: Severity = Severity.NONE) -> Evidence:
    return Evidence(
        check="test_check",
        category=CheckCategory.FORMAT_VALIDATION,
        status=status,
        confidence=0.8,
        severity=severity,
        message="test",
    )


class TestRiskAggregation:
    def test_empty_checks(self):
        risk = aggregate_evidence([])
        assert risk.risk_score == 0

    def test_all_passed(self):
        checks = [_make_check(CheckStatus.PASSED) for _ in range(5)]
        risk = aggregate_evidence(checks)
        assert risk.risk_score == 0
        assert risk.level == "low"

    def test_critical_failure(self):
        checks = [
            _make_check(CheckStatus.PASSED),
            _make_check(CheckStatus.FAILED, Severity.CRITICAL),
        ]
        risk = aggregate_evidence(checks)
        assert risk.risk_score > 0

    def test_warnings_add_risk(self):
        checks = [_make_check(CheckStatus.WARNING, Severity.MEDIUM) for _ in range(3)]
        risk = aggregate_evidence(checks)
        assert risk.risk_score > 0

    def test_all_unavailable(self):
        checks = [_make_check(CheckStatus.UNAVAILABLE) for _ in range(3)]
        risk = aggregate_evidence(checks)
        assert risk.level == "unknown"


class TestOverallStatus:
    def test_no_checks(self):
        status = determine_overall_status(
            aggregate_evidence([]), [], [],
        )
        assert status == OverallStatus.INSUFFICIENT_EVIDENCE

    def test_all_passed(self):
        checks = [_make_check(CheckStatus.PASSED) for _ in range(5)]
        risk = aggregate_evidence(checks)
        status = determine_overall_status(risk, checks, [])
        assert status == OverallStatus.LIKELY_VALID

    def test_critical_fail(self):
        checks = [
            _make_check(CheckStatus.FAILED, Severity.CRITICAL),
            _make_check(CheckStatus.PASSED),
        ]
        risk = aggregate_evidence(checks)
        status = determine_overall_status(risk, checks, [])
        assert status == OverallStatus.INVALID

    def test_warnings(self):
        checks = [_make_check(CheckStatus.WARNING, Severity.LOW)]
        risk = aggregate_evidence(checks)
        status = determine_overall_status(risk, checks, [])
        assert status == OverallStatus.VALID_WITH_WARNINGS


class TestSimplifyStatus:
    """Tests for the presentation-layer status mapping."""

    def test_likely_valid(self):
        assert simplify_status(OverallStatus.LIKELY_VALID) == "LIKELY VALID"

    def test_valid_with_warnings(self):
        assert simplify_status(OverallStatus.VALID_WITH_WARNINGS) == "INSUFFICIENT EVIDENCE"

    def test_anomalous(self):
        assert simplify_status(OverallStatus.ANOMALOUS) == "INSUFFICIENT EVIDENCE"

    def test_requires_review(self):
        assert simplify_status(OverallStatus.REQUIRES_REVIEW) == "INSUFFICIENT EVIDENCE"

    def test_invalid(self):
        assert simplify_status(OverallStatus.INVALID) == "INVALID / FRAUD DETECTED"

    def test_insufficient_evidence(self):
        assert simplify_status(OverallStatus.INSUFFICIENT_EVIDENCE) == "INSUFFICIENT EVIDENCE"

    def test_all_map_to_three_values(self):
        """Every OverallStatus must map to exactly one of the three display strings."""
        allowed = {"LIKELY VALID", "INVALID / FRAUD DETECTED", "INSUFFICIENT EVIDENCE"}
        for status in OverallStatus:
            assert simplify_status(status) in allowed

    def test_display_status_appears_in_api_response(self):
        """AnalysisResponse serialization includes display_status derived from overall_status."""
        from app.models import AnalysisResponse
        resp = AnalysisResponse(overall_status=OverallStatus.LIKELY_VALID)
        data = resp.model_dump()
        assert data["display_status"] == "LIKELY VALID"
        assert data["overall_status"] == "likely_valid"


class TestRiskScoreProportionality:
    """Regression tests for the ratio-form scoring bug.

    The old score was accumulated_risk / total_weight * 100. Severity is only
    ever assigned to checks that fail, so the denominator was built from the
    same set as the numerator and any single failure divided out to exactly
    100 — a LOW warning and a CRITICAL checksum failure were indistinguishable.
    """

    @staticmethod
    def _check(status, severity=Severity.NONE, confidence=0.9):
        return Evidence(
            check="c",
            category=CheckCategory.FORMAT_VALIDATION,
            status=status,
            confidence=confidence,
            severity=severity,
        )

    def test_severity_is_distinguishable(self):
        low = aggregate_evidence([self._check(CheckStatus.FAILED, Severity.LOW)])
        med = aggregate_evidence([self._check(CheckStatus.FAILED, Severity.MEDIUM)])
        high = aggregate_evidence([self._check(CheckStatus.FAILED, Severity.HIGH)])
        crit = aggregate_evidence([self._check(CheckStatus.FAILED, Severity.CRITICAL)])
        scores = [low.risk_score, med.risk_score, high.risk_score, crit.risk_score]
        assert scores == sorted(scores), scores
        assert len(set(scores)) == 4, f"severities collapsed to the same score: {scores}"

    def test_lone_low_warning_is_not_elevated(self):
        risk = aggregate_evidence([self._check(CheckStatus.WARNING, Severity.LOW)])
        assert risk.risk_score < 15
        assert risk.level == "low"

    def test_critical_failure_is_not_diluted_by_passing_checks(self):
        checks = [self._check(CheckStatus.FAILED, Severity.CRITICAL)]
        checks += [self._check(CheckStatus.PASSED) for _ in range(20)]
        assert aggregate_evidence(checks).risk_score >= 90

    def test_unavailable_checks_do_not_lower_risk(self):
        """Missing evidence used to read as safety: a critical failure beside
        three unavailable checks scored 25 ("moderate") next to an INVALID
        verdict."""
        alone = aggregate_evidence([self._check(CheckStatus.FAILED, Severity.CRITICAL)])
        with_gaps = aggregate_evidence(
            [self._check(CheckStatus.FAILED, Severity.CRITICAL)]
            + [self._check(CheckStatus.UNAVAILABLE, Severity.CRITICAL) for _ in range(3)]
        )
        assert with_gaps.risk_score == alone.risk_score

    def test_missing_evidence_lowers_confidence_instead(self):
        full = aggregate_evidence([self._check(CheckStatus.PASSED) for _ in range(4)])
        partial = aggregate_evidence(
            [self._check(CheckStatus.PASSED)]
            + [self._check(CheckStatus.UNAVAILABLE) for _ in range(3)]
        )
        assert partial.confidence < full.confidence
        assert partial.checks_determinate == 1
        assert partial.checks_total == 4

    def test_per_check_confidence_is_used(self):
        sure = aggregate_evidence([self._check(CheckStatus.PASSED, confidence=1.0)])
        unsure = aggregate_evidence([self._check(CheckStatus.PASSED, confidence=0.4)])
        assert sure.confidence > unsure.confidence

    def test_level_never_contradicts_a_critical_failure(self):
        checks = [self._check(CheckStatus.FAILED, Severity.CRITICAL)]
        checks += [self._check(CheckStatus.UNAVAILABLE, Severity.HIGH) for _ in range(5)]
        risk = aggregate_evidence(checks)
        status = determine_overall_status(risk, checks, [])
        assert risk.level == "high"
        assert status == OverallStatus.INVALID


# ---------------------------------------------------------------------------
# Regression: a verdict of "likely valid" requires actual evidence.
#
# determine_overall_status used to treat only UNAVAILABLE as "this check could
# not speak", while CheckStatus has three such values. A run whose checks were
# all NOT_APPLICABLE therefore had no failures, no warnings and no reviews, and
# fell through to LIKELY_VALID — the API asserting validity having determined
# nothing at all. Reachable from the UI by typing sixteen 1s, which classifies
# as a generic identifier with no applicable check.
# ---------------------------------------------------------------------------

def _status_for(checks: list[Evidence]) -> OverallStatus:
    return determine_overall_status(aggregate_evidence(checks), checks, [])


def test_all_not_applicable_is_insufficient_not_valid():
    checks = [_make_check(CheckStatus.NOT_APPLICABLE)]
    assert _status_for(checks) == OverallStatus.INSUFFICIENT_EVIDENCE


def test_every_non_determinate_status_is_insufficient():
    for status in (
        CheckStatus.NOT_APPLICABLE,
        CheckStatus.UNKNOWN,
        CheckStatus.UNAVAILABLE,
    ):
        checks = [_make_check(status), _make_check(status)]
        assert _status_for(checks) == OverallStatus.INSUFFICIENT_EVIDENCE, status


def test_mixed_non_determinate_statuses_are_insufficient():
    """No single status dominates, but nothing determined anything either."""
    checks = [
        _make_check(CheckStatus.NOT_APPLICABLE),
        _make_check(CheckStatus.UNKNOWN),
        _make_check(CheckStatus.UNAVAILABLE),
    ]
    assert _status_for(checks) == OverallStatus.INSUFFICIENT_EVIDENCE


def test_zero_determinate_checks_reported_as_zero():
    checks = [_make_check(CheckStatus.NOT_APPLICABLE)]
    risk = aggregate_evidence(checks)
    assert risk.checks_determinate == 0
    assert risk.checks_total == 1


def test_one_real_pass_still_yields_likely_valid():
    """The guard must not over-correct: real evidence still earns a verdict."""
    assert _status_for([_make_check(CheckStatus.PASSED)]) == OverallStatus.LIKELY_VALID


def test_pass_alongside_not_applicable_still_yields_likely_valid():
    checks = [_make_check(CheckStatus.PASSED), _make_check(CheckStatus.NOT_APPLICABLE)]
    assert _status_for(checks) == OverallStatus.LIKELY_VALID
