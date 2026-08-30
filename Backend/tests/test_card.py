"""Tests for card validation: Luhn, format, network detection."""

import pytest
from app.engines.card import detect_network, format_check, luhn_check, mask_card_number
from app.models import CheckStatus


class TestLuhnCheck:
    def test_valid_visa(self):
        result = luhn_check("4532015112830366")
        assert result.status == CheckStatus.PASSED

    def test_valid_amex(self):
        result = luhn_check("378282246310005")
        assert result.status == CheckStatus.PASSED

    def test_invalid_number(self):
        result = luhn_check("1234567890123456")
        assert result.status == CheckStatus.FAILED

    def test_with_spaces(self):
        result = luhn_check("4532 0151 1283 0366")
        assert result.status == CheckStatus.PASSED

    def test_with_hyphens(self):
        result = luhn_check("4532-0151-1283-0366")
        assert result.status == CheckStatus.PASSED

    def test_too_short(self):
        result = luhn_check("1234567")
        assert result.status == CheckStatus.WARNING

    def test_non_numeric(self):
        result = luhn_check("abcdef")
        assert result.status == CheckStatus.NOT_APPLICABLE

    def test_empty(self):
        result = luhn_check("")
        assert result.status == CheckStatus.NOT_APPLICABLE


class TestFormatCheck:
    def test_valid_with_separators(self):
        results = format_check("4532 0151 1283 0366")
        assert any(r.status == CheckStatus.PASSED for r in results)

    def test_too_short(self):
        results = format_check("12345")
        failed = [r for r in results if r.status == CheckStatus.FAILED]
        assert len(failed) > 0

    def test_non_numeric_rejected(self):
        results = format_check("abcd-efgh-ijkl")
        failed = [r for r in results if r.status == CheckStatus.FAILED]
        assert len(failed) > 0


class TestNetworkDetection:
    def test_visa(self):
        result = detect_network("4532015112830366")
        assert result.details.get("network") == "visa"

    def test_amex(self):
        result = detect_network("378282246310005")
        assert result.details.get("network") == "amex"

    def test_unknown(self):
        result = detect_network("1234567890123456")
        assert result.status.value == "unknown"


class TestMasking:
    def test_mask_card(self):
        masked = mask_card_number("4532015112830366")
        assert masked == "**** **** **** 0366"

    def test_mask_short(self):
        masked = mask_card_number("12")
        assert masked == "**"


class TestDegenerateSequence:
    """Placeholder numbers that satisfy Luhn without being issued cards.

    Luhn is a transcription-error check, not proof of issuance. All-zeros sums
    to zero and zero is divisible by ten, so it passes — which made a common
    mockup number report as a likely-valid card.
    """

    def test_all_zeros_fails_despite_passing_luhn(self):
        from app.engines.card import degenerate_check, luhn_valid

        assert luhn_valid("0000000000000000") is True, "precondition: Luhn accepts it"
        assert degenerate_check("0000000000000000").status == CheckStatus.FAILED

    @pytest.mark.parametrize("number", [
        "0000000000000000",
        "1111111111111111",
        "9999999999999999",
        "4444444444444444",
    ])
    def test_repeated_digits_rejected(self, number):
        from app.engines.card import degenerate_check

        result = degenerate_check(number)
        assert result.status == CheckStatus.FAILED
        assert result.details["pattern"] == "repeated_digit"

    @pytest.mark.parametrize("number", ["123456789", "987654321"])
    def test_strict_runs_rejected(self, number):
        from app.engines.card import degenerate_check

        assert degenerate_check(number).status == CheckStatus.FAILED

    @pytest.mark.parametrize("number", [
        "4111111111111111",   # standard Visa test number
        "5555555555554444",   # standard Mastercard test number
        "378282246310005",    # standard Amex test number
    ])
    def test_real_test_cards_pass(self, number):
        """Must not flag legitimate numbers — 5555...4444 repeats heavily but
        is not a single repeated digit."""
        from app.engines.card import degenerate_check

        assert degenerate_check(number).status == CheckStatus.PASSED

    def test_non_numeric_is_not_applicable(self):
        from app.engines.card import degenerate_check

        assert degenerate_check("not-a-card").status == CheckStatus.NOT_APPLICABLE

    def test_all_zeros_is_invalid_end_to_end(self):
        from app.orchestrator import analyze_single_value

        resp = analyze_single_value("0000 0000 0000 0000", confirmed_value_type="card_number")
        assert resp.overall_status.value == "invalid"


# ---------------------------------------------------------------------------
# Regression: published test card numbers must not report as likely valid.
#
# 4111 1111 1111 1111 is the most widely published test PAN in existence. It has
# mixed digits, satisfies Luhn, and matches Visa's numbering rules, so every
# structural check passes it and the app reported "Likely Valid" — for the one
# sixteen-digit string a reviewer is most likely to try, and the exact value in
# this app's own input placeholder.
# ---------------------------------------------------------------------------

from app.engines.card import published_test_card_check


def test_canonical_visa_test_number_is_flagged():
    ev = published_test_card_check("4111111111111111")
    assert ev.status == CheckStatus.WARNING
    assert "test card number" in ev.message.lower()


def test_test_card_detection_ignores_formatting():
    assert published_test_card_check("4111 1111 1111 1111").status == CheckStatus.WARNING
    assert published_test_card_check("4111-1111-1111-1111").status == CheckStatus.WARNING


def test_test_numbers_across_networks_are_flagged():
    for pan in (
        "4242424242424242",      # Visa / Stripe
        "5555555555554444",      # Mastercard
        "378282246310005",       # American Express
        "6011111111111117",      # Discover
        "3530111333300000",      # JCB
        "30569309025904",        # Diners Club
    ):
        assert published_test_card_check(pan).status == CheckStatus.WARNING, pan


def test_a_real_looking_card_is_not_flagged():
    """The check must not fire on ordinary Luhn-valid numbers."""
    ev = published_test_card_check("4539578763621486")
    assert ev.status == CheckStatus.PASSED


def test_test_card_check_is_not_applicable_without_digits():
    assert published_test_card_check("no digits here").status == CheckStatus.NOT_APPLICABLE
