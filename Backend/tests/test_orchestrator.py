"""Tests for the unified orchestrator."""

from unittest.mock import MagicMock, patch

from app.orchestrator import analyze_dataset, analyze_document_text, analyze_single_value
from app.models import OverallStatus


class TestSingleValue:
    def test_financial_amount(self):
        resp = analyze_single_value("$1499.00")
        assert resp.input_classification is not None
        assert resp.input_classification.type == "financial_amount"

    def test_card_number(self):
        resp = analyze_single_value("4532015112830366")
        assert resp.input_classification is not None
        assert resp.input_classification.type == "card_number"
        assert "masked_number" in resp.extracted_data

    def test_date(self):
        resp = analyze_single_value("2026-08-18")
        assert resp.input_classification is not None
        assert resp.input_classification.type == "date"

    def test_unknown_text(self):
        resp = analyze_single_value("hello world")
        assert resp.input_classification is not None
        assert resp.input_classification.type == "unknown"


class TestDataset:
    def test_benford_like(self):
        numbers = []
        from app.benford import expected_frequency
        for d in range(1, 10):
            count = int(30 * expected_frequency(d))
            for _ in range(count):
                numbers.append(float(d * 100 + 50))
        resp = analyze_dataset(numbers)
        assert resp.statistical_analysis != {}

    def test_small_dataset(self):
        resp = analyze_dataset([1.0, 2.0, 3.0])
        assert any("small" in lim.lower() or "insufficient" in lim.lower() for lim in resp.limitations)

    def test_two_digit_benford_included(self):
        numbers = [float(x) for x in range(100, 300)]
        resp = analyze_dataset(numbers)
        assert "benford_two_digit" in resp.statistical_analysis
        two_digit = resp.statistical_analysis["benford_two_digit"]
        assert isinstance(two_digit, dict)
        assert "chi_square" in two_digit

    def test_two_digit_chi_square_check_present(self):
        numbers = [float(x) for x in range(100, 200)]
        resp = analyze_dataset(numbers)
        check_names = [c.check for c in resp.checks]
        assert "benford_two_digit_chi_square" in check_names


class TestDocumentText:
    def test_with_numbers(self):
        text = "\n".join([f"${i * 100}" for i in range(60)])
        resp = analyze_document_text(text, source_type="manual_text")
        assert int(str(resp.extracted_data.get("numbers_found", 0))) > 0

    def test_empty_text(self):
        resp = analyze_document_text("", source_type="manual_text")
        assert resp.overall_status in (
            OverallStatus.INSUFFICIENT_EVIDENCE,
            OverallStatus.INVALID,
        )


class TestGroqIntegration:
    def test_explanation_fallback_without_groq(self):
        with patch("app.orchestrator.get_groq_client") as mock_get:
            mock_client = MagicMock()
            mock_client.available = False
            mock_get.return_value = mock_client
            resp = analyze_single_value("4532015112830366")
            assert resp.explanation != ""

    def test_explanation_enhanced_with_groq(self):
        with patch("app.orchestrator.get_groq_client") as mock_get:
            mock_client = MagicMock()
            mock_client.available = True
            mock_client.chat.return_value = "AI-enhanced explanation."
            mock_get.return_value = mock_client
            resp = analyze_single_value("4532015112830366")
            assert resp.explanation == "AI-enhanced explanation."
            mock_client.chat.assert_called_once()

    def test_groq_failure_falls_back_to_deterministic(self):
        with patch("app.orchestrator.get_groq_client") as mock_get:
            mock_client = MagicMock()
            mock_client.available = True
            mock_client.chat.return_value = None
            mock_get.return_value = mock_client
            resp = analyze_single_value("4532015112830366")
            assert resp.explanation != ""

    def test_dataset_groq_enhanced(self):
        with patch("app.orchestrator.get_groq_client") as mock_get:
            mock_client = MagicMock()
            mock_client.available = True
            mock_client.chat.return_value = "Dataset AI summary."
            mock_get.return_value = mock_client
            resp = analyze_dataset([float(x) for x in range(100, 200)])
            assert resp.explanation == "Dataset AI summary."

    def test_groq_never_mandatory(self):
        with patch("app.orchestrator.get_groq_client") as mock_get:
            mock_client = MagicMock()
            mock_client.available = False
            mock_get.return_value = mock_client
            resp = analyze_dataset([float(x) for x in range(100, 200)])
            assert resp.overall_status is not None
            assert resp.risk_assessment is not None


class TestOptionalDependencies:
    def test_xlsx_missing_openpyxl(self):
        import sys
        with patch.dict(sys.modules, {"openpyxl": None}):
            from app.ingestion.csv_xlsx import read_xlsx
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
                f.write(b"fake")
                f.flush()
                try:
                    import pytest
                    with pytest.raises(FileNotFoundError, match="openpyxl"):
                        read_xlsx(f.name)
                finally:
                    import os
                    os.unlink(f.name)

    def test_pdf_missing_pymupdf(self):
        with patch.dict("sys.modules", {"pymupdf": None}):
            from app.ingestion.pdf import extract_text_from_pdf
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(b"fake")
                f.flush()
                try:
                    result, exact = extract_text_from_pdf(f.name)
                    assert result == ""
                    assert exact is False
                finally:
                    import os
                    os.unlink(f.name)

    def test_xlsx_upload_missing_openpyxl(self):
        with patch("app.orchestrator.get_groq_client") as mock_get:
            mock_client = MagicMock()
            mock_client.available = False
            mock_get.return_value = mock_client
            with patch("app.ingestion.csv_xlsx.read_xlsx", side_effect=FileNotFoundError("openpyxl required")):
                from app.orchestrator import _analyze_xlsx
                resp = _analyze_xlsx("/fake/file.xlsx")
                assert resp.overall_status == OverallStatus.INVALID
                assert any("openpyxl" in lim for lim in resp.limitations)


class TestCsvSecondaryColumns:
    """_analyze_csv only runs Benford's Law on the single largest numeric
    column; fabricated data confined to a smaller column would otherwise be
    invisible. These lock in the secondary-column flag added to close that gap.
    """

    @staticmethod
    def _write_csv(primary: list[int], secondary: list[int]) -> str:
        import csv
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f:
            writer = csv.writer(f)
            writer.writerow(["primary", "secondary"])
            for p, s in zip(primary, secondary):
                writer.writerow([p, s])
            return f.name

    def test_flags_anomalous_secondary_column(self):
        import os
        from app.benford import expected_frequency
        from app.orchestrator import _analyze_csv

        # Primary column: roughly Benford-conforming, and the largest column,
        # so it's the one selected as the primary analyzed column.
        primary: list[int] = []
        for d in range(1, 10):
            count = int(100 * expected_frequency(d))
            for _ in range(count):
                primary.append(d * 100 + 50)

        # Secondary column: same length, but every value starts with digit 9 —
        # a strong Benford violation that would previously go undetected
        # entirely because only the primary column was ever analyzed.
        secondary = [900 + i for i in range(len(primary))]

        path = self._write_csv(primary, secondary)
        try:
            resp = _analyze_csv(path)
        finally:
            os.unlink(path)

        secondary_checks = [c for c in resp.checks if c.check == "benford_chi_square_secondary_column"]
        assert secondary_checks, "expected a flagged check for the anomalous secondary column"
        assert secondary_checks[0].details["column"] == "secondary"
        assert any("secondary" in lim for lim in resp.limitations)

    def test_no_flag_when_secondary_column_conforms(self):
        import os
        from app.benford import expected_frequency
        from app.orchestrator import _analyze_csv

        primary: list[int] = []
        secondary: list[int] = []
        for d in range(1, 10):
            count = int(100 * expected_frequency(d))
            for _ in range(count):
                primary.append(d * 100 + 50)
                secondary.append(d * 100 + 60)

        path = self._write_csv(primary, secondary)
        try:
            resp = _analyze_csv(path)
        finally:
            os.unlink(path)

        secondary_checks = [c for c in resp.checks if c.check == "benford_chi_square_secondary_column"]
        assert not secondary_checks
