"""Tests for CNIC (Pakistani National Identity Card) validation.

A CNIC carries no check digit. Unlike Luhn on a card or the ICAO 9303 composite
on a passport, there is no arithmetic that can confirm the number was issued, so
these tests deliberately pin down the *ceiling* of what the engine may claim: it
can prove a number malformed, and it must never report a well-formed one as
valid. The whole point of the suite is that the honest ceiling stays enforced.
"""

from __future__ import annotations

import pytest

from app.models import CheckStatus, OverallStatus, Severity


# A structurally sound CNIC: province 3 (Punjab), odd final digit (male).
VALID_CNIC = "3520212345671"
# Province 4 (Sindh), even final digit (female).
VALID_CNIC_FEMALE = "4210987654322"


# ---------------------------------------------------------------------------
# 1. Format: length and numeric composition
# ---------------------------------------------------------------------------

class TestCnicFormatCheck:
    def test_thirteen_digits_passes(self):
        from app.engines.cnic import format_check

        ev = format_check(VALID_CNIC)
        assert ev.status == CheckStatus.PASSED

    def test_dashed_presentation_form_passes(self):
        """35202-1234567-1 is how a CNIC is printed; separators are not errors."""
        from app.engines.cnic import format_check

        ev = format_check("35202-1234567-1")
        assert ev.status == CheckStatus.PASSED

    def test_spaced_form_passes(self):
        from app.engines.cnic import format_check

        ev = format_check("35202 1234567 1")
        assert ev.status == CheckStatus.PASSED

    def test_twelve_digits_fails(self):
        from app.engines.cnic import format_check

        ev = format_check("352021234567")
        assert ev.status == CheckStatus.FAILED
        assert ev.severity == Severity.CRITICAL
        assert "12" in ev.message

    def test_fourteen_digits_fails(self):
        from app.engines.cnic import format_check

        ev = format_check("35202123456712")
        assert ev.status == CheckStatus.FAILED
        assert ev.severity == Severity.CRITICAL

    def test_letters_fail(self):
        from app.engines.cnic import format_check

        ev = format_check("35202ABC45671")
        assert ev.status == CheckStatus.FAILED

    def test_empty_is_not_applicable(self):
        """No input is an absence of evidence, never a finding of invalidity."""
        from app.engines.cnic import format_check

        ev = format_check("")
        assert ev.status == CheckStatus.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# 2. Province / region code (first digit)
# ---------------------------------------------------------------------------

class TestProvinceCheck:
    @pytest.mark.parametrize("first_digit,region", [
        ("1", "Khyber Pakhtunkhwa"),
        ("2", "FATA"),
        ("3", "Punjab"),
        ("4", "Sindh"),
        ("5", "Balochistan"),
        ("6", "Islamabad"),
        ("7", "Gilgit-Baltistan"),
    ])
    def test_every_issued_region_code_passes(self, first_digit, region):
        from app.engines.cnic import province_check

        ev = province_check(first_digit + "520212345670")
        assert ev.status == CheckStatus.PASSED
        assert ev.details.get("region") == region

    def test_zero_prefix_fails(self):
        from app.engines.cnic import province_check

        ev = province_check("0520212345671")
        assert ev.status == CheckStatus.FAILED
        assert ev.severity == Severity.CRITICAL

    @pytest.mark.parametrize("bad", ["8", "9"])
    def test_unassigned_region_code_fails(self, bad):
        from app.engines.cnic import province_check

        ev = province_check(bad + "520212345671")
        assert ev.status == CheckStatus.FAILED

    def test_wrong_length_is_not_applicable(self):
        """Region code means nothing on a number that isn't a CNIC shape."""
        from app.engines.cnic import province_check

        ev = province_check("352")
        assert ev.status == CheckStatus.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# 3. Gender digit (final digit) — descriptive, never a validity signal
# ---------------------------------------------------------------------------

class TestGenderDigitCheck:
    def test_odd_final_digit_reads_male(self):
        from app.engines.cnic import gender_digit_check

        ev = gender_digit_check(VALID_CNIC)
        assert ev.status == CheckStatus.PASSED
        assert ev.details.get("gender") == "male"

    def test_even_final_digit_reads_female(self):
        from app.engines.cnic import gender_digit_check

        ev = gender_digit_check(VALID_CNIC_FEMALE)
        assert ev.status == CheckStatus.PASSED
        assert ev.details.get("gender") == "female"

    def test_gender_digit_never_carries_severity(self):
        """The final digit encodes gender, not correctness. It cannot fail."""
        from app.engines.cnic import gender_digit_check

        for cnic in (VALID_CNIC, VALID_CNIC_FEMALE):
            ev = gender_digit_check(cnic)
            assert ev.severity == Severity.NONE


# ---------------------------------------------------------------------------
# 4. Degenerate placeholder sequences
# ---------------------------------------------------------------------------

class TestDegenerateCheck:
    def test_all_same_digit_fails(self):
        from app.engines.cnic import degenerate_check

        ev = degenerate_check("1111111111111")
        assert ev.status == CheckStatus.FAILED
        assert ev.severity == Severity.CRITICAL

    def test_strict_ascending_run_fails(self):
        from app.engines.cnic import degenerate_check

        ev = degenerate_check("1234567890123")
        assert ev.status == CheckStatus.FAILED

    def test_ordinary_number_passes(self):
        from app.engines.cnic import degenerate_check

        ev = degenerate_check(VALID_CNIC)
        assert ev.status == CheckStatus.PASSED


# ---------------------------------------------------------------------------
# 5. The honesty ceiling: no checksum exists, so nothing may be called valid
# ---------------------------------------------------------------------------

class TestAuthorityVerificationNote:
    def test_note_requires_review_even_for_a_well_formed_number(self):
        from app.engines.cnic import authority_verification_note

        ev = authority_verification_note(VALID_CNIC)
        assert ev.status == CheckStatus.REQUIRES_REVIEW

    def test_note_explains_that_no_check_digit_exists(self):
        from app.engines.cnic import authority_verification_note

        ev = authority_verification_note(VALID_CNIC)
        assert "check digit" in ev.message.lower()


# ---------------------------------------------------------------------------
# 6. Presentation helpers
# ---------------------------------------------------------------------------

class TestPresentation:
    def test_format_cnic_uses_official_grouping(self):
        from app.engines.cnic import format_cnic

        assert format_cnic(VALID_CNIC) == "35202-1234567-1"

    def test_format_cnic_leaves_wrong_length_alone(self):
        from app.engines.cnic import format_cnic

        assert format_cnic("352") == "352"

    def test_mask_cnic_hides_the_serial(self):
        """The 7-digit family/serial block is the identifying part."""
        from app.engines.cnic import mask_cnic

        masked = mask_cnic(VALID_CNIC)
        assert "1234567" not in masked
        assert masked.startswith("35202")
        assert masked.endswith("1")


# ---------------------------------------------------------------------------
# 7. Orchestrator integration
# ---------------------------------------------------------------------------

class TestCnicOrchestration:
    def test_well_formed_cnic_is_never_likely_valid(self):
        """The core honesty guarantee: no checksum means no assertion of validity."""
        from app.orchestrator import analyze_single_value

        resp = analyze_single_value(VALID_CNIC, confirmed_value_type="cnic")
        assert resp.overall_status != OverallStatus.LIKELY_VALID
        assert resp.overall_status == OverallStatus.REQUIRES_REVIEW

    def test_well_formed_cnic_runs_the_cnic_checks(self):
        from app.orchestrator import analyze_single_value

        resp = analyze_single_value(VALID_CNIC, confirmed_value_type="cnic")
        names = {c.check for c in resp.checks}
        assert "cnic_format" in names
        assert "cnic_region_code" in names
        assert "cnic_gender_digit" in names
        assert "cnic_authority_verification" in names

    def test_invalid_region_code_is_invalid_overall(self):
        from app.orchestrator import analyze_single_value

        resp = analyze_single_value("9520212345671", confirmed_value_type="cnic")
        assert resp.overall_status == OverallStatus.INVALID
        assert resp.risk_assessment is not None
        assert resp.risk_assessment.risk_score >= 70

    def test_wrong_length_is_invalid_overall(self):
        from app.orchestrator import analyze_single_value

        resp = analyze_single_value("352021234567", confirmed_value_type="cnic")
        assert resp.overall_status == OverallStatus.INVALID

    def test_placeholder_cnic_is_invalid_overall(self):
        from app.orchestrator import analyze_single_value

        resp = analyze_single_value("1111111111111", confirmed_value_type="cnic")
        assert resp.overall_status == OverallStatus.INVALID

    def test_dashed_input_is_accepted_end_to_end(self):
        from app.orchestrator import analyze_single_value

        resp = analyze_single_value("35202-1234567-1", confirmed_value_type="cnic")
        assert resp.overall_status == OverallStatus.REQUIRES_REVIEW

    def test_masked_cnic_is_exposed_not_the_raw_number(self):
        from app.orchestrator import analyze_single_value

        resp = analyze_single_value(VALID_CNIC, confirmed_value_type="cnic")
        assert "masked_cnic" in resp.extracted_data
        assert "1234567" not in str(resp.extracted_data["masked_cnic"])

    def test_limitations_state_that_authenticity_is_unverifiable(self):
        from app.orchestrator import analyze_single_value

        resp = analyze_single_value(VALID_CNIC, confirmed_value_type="cnic")
        assert any("NADRA" in lim or "authorit" in lim.lower() for lim in resp.limitations)


# ---------------------------------------------------------------------------
# 8. Classification: a bare 13-digit number is ambiguous, context resolves it
# ---------------------------------------------------------------------------

class TestCnicClassification:
    def test_cnic_context_produces_a_cnic_candidate(self):
        from app.orchestrator import classify_input

        resp = classify_input(VALID_CNIC, context="CNIC number")
        assert any(c.type == "cnic" for c in resp.value_candidates)

    def test_national_id_context_produces_a_cnic_candidate(self):
        from app.orchestrator import classify_input

        resp = classify_input(VALID_CNIC, context="Pakistani national identity card")
        assert any(c.type == "cnic" for c in resp.value_candidates)

    def test_cnic_context_outranks_the_card_reading(self):
        """13 digits also fits a card; the context is what breaks the tie."""
        from app.orchestrator import classify_input

        resp = classify_input(VALID_CNIC, context="CNIC number")
        assert resp.top_value_type == "cnic"

    def test_bare_thirteen_digits_is_not_assumed_to_be_a_cnic(self):
        """Without context there is nothing distinguishing a CNIC from any
        other 13-digit number, and guessing would be fabricated confidence."""
        from app.orchestrator import classify_input

        resp = classify_input(VALID_CNIC)
        assert resp.top_value_type != "cnic"
