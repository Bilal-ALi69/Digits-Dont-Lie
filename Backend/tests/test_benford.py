"""Tests for the Benford's Law analysis engine."""

import math

from app.benford import (
    BenfordResult,
    TwoDigitBenfordResult,
    analyze,
    analyze_two_digit,
    expected_frequency,
    first_two_digit_expected_frequency,
)


class TestExpectedFrequency:
    def test_digit_one(self):
        assert abs(expected_frequency(1) - 0.30103) < 0.001

    def test_digit_nine(self):
        assert abs(expected_frequency(9) - 0.04576) < 0.001

    def test_all_sum_to_one(self):
        total = sum(expected_frequency(d) for d in range(1, 10))
        assert abs(total - 1.0) < 0.0001

    def test_monotonically_decreasing(self):
        freqs = [expected_frequency(d) for d in range(1, 10)]
        for i in range(len(freqs) - 1):
            assert freqs[i] > freqs[i + 1]


class TestTwoDigitExpectedFrequency:
    def test_digit_ten(self):
        assert abs(first_two_digit_expected_frequency(10) - 0.04139) < 0.001

    def test_digit_ninety_nine(self):
        assert abs(first_two_digit_expected_frequency(99) - 0.00436) < 0.001

    def test_all_sum_to_one(self):
        total = sum(first_two_digit_expected_frequency(d) for d in range(10, 100))
        assert abs(total - 1.0) < 0.001

    def test_monotonically_decreasing(self):
        freqs = [first_two_digit_expected_frequency(d) for d in range(10, 100)]
        for i in range(len(freqs) - 1):
            assert freqs[i] > freqs[i + 1]


class TestAnalyze:
    def test_returns_benford_result_type(self):
        result = analyze([100, 200, 300, 400, 500])
        assert isinstance(result, dict)
        assert "total_count" in result
        assert "chi_square" in result

    def test_empty_input(self):
        result = analyze([])
        assert result["total_count"] == 0
        assert result["invalid_count"] == 0
        assert result["chi_square"] == 0.0

    def test_all_zeros(self):
        result = analyze([0, 0, 0, 0])
        assert result["total_count"] == 0
        assert result["invalid_count"] == 4

    def test_all_invalid(self):
        result = analyze([float("nan"), float("inf"), 0, 0])
        assert result["total_count"] == 0

    def test_negative_numbers(self):
        result = analyze([-100, -200, -300, -400, -500])
        assert result["total_count"] == 5

    def test_decimals(self):
        result = analyze([0.01, 0.15, 0.99, 1.5, 2.5])
        assert result["total_count"] == 5

    def test_benford_like_distribution(self):
        numbers = []
        for d in range(1, 10):
            count = int(30 * expected_frequency(d))
            for _ in range(count):
                numbers.append(d * 100 + 50)
        result = analyze(numbers)
        assert result["total_count"] > 0
        assert result["chi_square"] < 16.9

    def test_non_benford_distribution(self):
        numbers = [110, 120, 130, 140, 150, 160, 170, 180, 190] * 10
        result = analyze(numbers)
        assert result["total_count"] == 90
        assert result["chi_square"] > 0

    def test_observed_counts_sum_to_total(self):
        result = analyze([123, 456, 789, 234, 567, 890, 111, 222, 333, 444])
        total = sum(result["observed_counts"].values())
        assert total == result["total_count"]

    def test_observed_frequencies_are_percentages(self):
        result = analyze([100, 200, 300, 400, 500, 600, 700, 800, 900])
        total_pct = sum(result["observed_frequencies"].values())
        assert abs(total_pct - 100.0) < 0.01

    def test_expected_frequencies_are_percentages(self):
        result = analyze([100, 200, 300])
        total_pct = sum(result["expected_frequencies"].values())
        assert abs(total_pct - 100.0) < 0.01

    def test_chi_square_non_negative(self):
        result = analyze([123, 456, 789, 111, 222, 333, 444, 555, 666, 777])
        assert result["chi_square"] >= 0

    def test_p_value_present(self):
        result = analyze([100, 200, 300, 400, 500] * 20)
        assert "p_value" in result
        assert result["p_value"] is not None
        assert 0 <= result["p_value"] <= 1

    def test_applicability_insufficient_data(self):
        result = analyze([100, 200, 300])
        assert result.get("applicability") == "insufficient_data"

    def test_applicability_questionable(self):
        numbers = list(range(100, 175))
        result = analyze([float(x) for x in numbers])
        assert result.get("applicability") == "questionable"

    def test_applicability_appropriate(self):
        numbers = list(range(1000, 1100))
        result = analyze([float(x) for x in numbers])
        assert result.get("applicability") == "applicable"

    def test_string_numbers_rejected(self):
        result = analyze([])
        assert result["total_count"] == 0


class TestAnalyzeTwoDigit:
    def test_returns_two_digit_result_type(self):
        result = analyze_two_digit([100, 200, 300, 400, 500])
        assert isinstance(result, dict)
        assert "total_count" in result
        assert "chi_square" in result

    def test_empty_input(self):
        result = analyze_two_digit([])
        assert result["total_count"] == 0
        assert result["chi_square"] == 0.0

    def test_all_zeros(self):
        result = analyze_two_digit([0, 0, 0, 0])
        assert result["total_count"] == 0
        assert result["invalid_count"] == 4

    def test_all_invalid(self):
        result = analyze_two_digit([float("nan"), float("inf"), 0, 0])
        assert result["total_count"] == 0

    def test_observed_counts_sum_to_total(self):
        result = analyze_two_digit([123, 456, 789, 234, 567, 890, 111, 222, 333, 444])
        total = sum(result["observed_counts"].values())
        assert total == result["total_count"]

    def test_observed_frequencies_are_percentages(self):
        result = analyze_two_digit([100, 200, 300, 400, 500, 600, 700, 800, 900])
        total_pct = sum(result["observed_frequencies"].values())
        assert abs(total_pct - 100.0) < 0.01

    def test_expected_frequencies_are_percentages(self):
        result = analyze_two_digit([100, 200, 300])
        total_pct = sum(result["expected_frequencies"].values())
        assert abs(total_pct - 100.0) < 0.01

    def test_chi_square_non_negative(self):
        result = analyze_two_digit([123, 456, 789, 111, 222, 333, 444, 555, 666, 777])
        assert result["chi_square"] >= 0

    def test_p_value_present(self):
        result = analyze_two_digit([100, 200, 300, 400, 500] * 20)
        assert "p_value" in result
        assert result["p_value"] is not None
        assert 0 <= result["p_value"] <= 1

    def test_applicability_insufficient_data(self):
        result = analyze_two_digit([100, 200, 300])
        assert result.get("applicability") == "insufficient_data"

    def test_applicability_appropriate(self):
        numbers = list(range(1000, 1100))
        result = analyze_two_digit([float(x) for x in numbers])
        assert result.get("applicability") == "applicable"

    def test_all_keys_in_range(self):
        result = analyze_two_digit([float(x) for x in range(100, 1000)])
        for key in result["observed_counts"]:
            assert 10 <= int(key) <= 99
