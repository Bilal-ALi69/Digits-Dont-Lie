"""Tests for the preprocessing / leading digit extraction."""

from app.preprocess import first_leading_digit, first_two_leading_digits


class TestFirstLeadingDigit:
    def test_positive_integers(self):
        assert first_leading_digit(123) == 1
        assert first_leading_digit(4567) == 4
        assert first_leading_digit(999) == 9

    def test_negative_integers(self):
        assert first_leading_digit(-123) == 1
        assert first_leading_digit(-999) == 9

    def test_zero(self):
        assert first_leading_digit(0) is None

    def test_decimals(self):
        assert first_leading_digit(0.45) == 4
        assert first_leading_digit(0.00123) == 1
        assert first_leading_digit(0.999) == 9

    def test_large_numbers(self):
        assert first_leading_digit(4500000) == 4
        assert first_leading_digit(999999999) == 9

    def test_small_numbers(self):
        assert first_leading_digit(0.000001) == 1

    def test_exactly_one(self):
        assert first_leading_digit(1) == 1

    def test_exactly_ten(self):
        assert first_leading_digit(10) == 1

    def test_nan(self):
        assert first_leading_digit(float("nan")) is None

    def test_inf(self):
        assert first_leading_digit(float("inf")) is None
        assert first_leading_digit(float("-inf")) is None

    def test_none(self):
        assert first_leading_digit(None) is None

    def test_string_number(self):
        assert first_leading_digit("123") == 1
        assert first_leading_digit("0.45") == 4

    def test_invalid_string(self):
        assert first_leading_digit("abc") is None

    def test_empty_string(self):
        assert first_leading_digit("") is None


class TestFirstTwoLeadingDigits:
    def test_small_integers(self):
        assert first_two_leading_digits(12) == 12
        assert first_two_leading_digits(99) == 99

    def test_large_integers(self):
        assert first_two_leading_digits(123) == 12
        assert first_two_leading_digits(4567) == 45
        assert first_two_leading_digits(999) == 99

    def test_hundreds(self):
        assert first_two_leading_digits(100) == 10
        assert first_two_leading_digits(500) == 50
        assert first_two_leading_digits(999) == 99

    def test_thousands(self):
        assert first_two_leading_digits(1000) == 10
        assert first_two_leading_digits(3456) == 34

    def test_decimals(self):
        assert first_two_leading_digits(0.45) == 45
        assert first_two_leading_digits(0.0123) == 12
        assert first_two_leading_digits(0.999) == 99

    def test_very_small(self):
        assert first_two_leading_digits(0.0000012) == 12

    def test_exactly_ten(self):
        assert first_two_leading_digits(10) == 10

    def test_exactly_ninety_nine(self):
        assert first_two_leading_digits(99) == 99

    def test_exactly_one(self):
        assert first_two_leading_digits(1) == 10

    def test_negative(self):
        assert first_two_leading_digits(-123) == 12
        assert first_two_leading_digits(-0.45) == 45

    def test_zero(self):
        assert first_two_leading_digits(0) is None

    def test_nan(self):
        assert first_two_leading_digits(float("nan")) is None

    def test_inf(self):
        assert first_two_leading_digits(float("inf")) is None
        assert first_two_leading_digits(float("-inf")) is None

    def test_none(self):
        assert first_two_leading_digits(None) is None

    def test_string_number(self):
        assert first_two_leading_digits("123") == 12
        assert first_two_leading_digits("0.45") == 45

    def test_invalid_string(self):
        assert first_two_leading_digits("abc") is None

    def test_empty_string(self):
        assert first_two_leading_digits("") is None

    def test_all_in_range(self):
        for i in range(10, 100):
            assert first_two_leading_digits(float(i)) == i
