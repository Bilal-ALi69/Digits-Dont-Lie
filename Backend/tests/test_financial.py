"""Tests for financial arithmetic verification."""

from app.engines.financial import verify_bank_balance, verify_invoice_totals
from app.models import CheckStatus


class TestInvoiceTotals:
    def test_correct_totals(self):
        items = [{"amount": 100.0}, {"amount": 200.0}, {"amount": 50.0}]
        results = verify_invoice_totals(
            items,
            expected_subtotal=350.0,
            tax_rate=0.1,
            expected_total=385.0,
        )
        assert all(r.status == CheckStatus.PASSED for r in results)

    def test_incorrect_subtotal(self):
        items = [{"amount": 100.0}, {"amount": 200.0}]
        results = verify_invoice_totals(items, expected_subtotal=500.0)
        failed = [r for r in results if r.status == CheckStatus.FAILED]
        assert len(failed) == 1

    def test_incorrect_total(self):
        items = [{"amount": 100.0}]
        results = verify_invoice_totals(
            items,
            expected_subtotal=100.0,
            tax_rate=0.1,
            expected_total=500.0,
        )
        failed = [r for r in results if r.status == CheckStatus.FAILED]
        assert len(failed) == 1

    def test_no_expectations(self):
        items = [{"amount": 100.0}]
        results = verify_invoice_totals(items)
        assert results == []


class TestBankBalance:
    def test_correct_balance(self):
        result = verify_bank_balance(opening=1000, credits=500, debits=300, closing=1200)
        assert result.status == CheckStatus.PASSED

    def test_incorrect_balance(self):
        result = verify_bank_balance(opening=1000, credits=500, debits=300, closing=9999)
        assert result.status == CheckStatus.FAILED

    def test_tolerance(self):
        result = verify_bank_balance(opening=1000, credits=333.33, debits=111.11, closing=1222.22)
        assert result.status == CheckStatus.PASSED
