"""Unified analysis orchestrator: routes input to appropriate engines."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.ocr import OcrCardCandidate
    from app.engines.classifier import VisionClassification

from app.benford import BenfordResult, analyze as benford_analyze, analyze_two_digit
from app.engines.card import (
    degenerate_check,
    detect_network,
    format_check,
    luhn_check,
    published_test_card_check,
    mask_card_number,
)
from app.engines.classifier import classify_with_candidates
from app.engines.cnic import (
    authority_verification_note as cnic_authority_note,
    degenerate_check as cnic_degenerate_check,
    format_check as cnic_format_check,
    format_cnic,
    gender_digit_check as cnic_gender_digit_check,
    mask_cnic,
    province_check as cnic_province_check,
)
from app.engines.cv import analyze_cv
from app.engines.groq_client import get_groq_client
from app.engines.invoice import (
    extract_invoice_fields,
    verify_extracted_document,
    verify_line_items,
)
from app.engines.risk import aggregate_evidence, determine_overall_status
from app.models import (
    AnalysisResponse,
    CheckCategory,
    CheckStatus,
    ClassificationCandidate,
    ClassificationResponse,
    Evidence,
    InputClassification,
    OverallStatus,
    Severity,
)


# Human labels for the raw value-type identifiers used throughout the pipeline.
#
# These identifiers are an internal vocabulary, but they were reaching users
# verbatim: the identifier_format check interpolated one straight into its
# message, so the checks list on the results screen read "Value treated as
# generic_identifier." Anything that ends up inside an Evidence.message or a
# limitation is display text and has to be written as display text.
_VALUE_TYPE_LABELS: dict[str, str] = {
    "card_number": "a card number",
    "financial_amount": "a financial amount",
    "invoice_number": "an invoice number",
    "invoice_reference": "an invoice reference",
    "transaction_id": "a transaction ID",
    "generic_identifier": "a generic identifier",
    "identifier": "an identifier",
    "id_number": "an ID number",
    "cnic": "a Pakistani CNIC",
    "passport_number": "a passport number",
    "license_number": "a licence number",
    "date": "a date",
    "financial_dataset": "a financial dataset",
    "numeric_dataset": "a numeric dataset",
    "dataset": "a dataset",
    "document": "a document",
    "unknown": "an unrecognised value",
}


def humanize_value_type(value_type: str) -> str:
    """Render an internal value-type identifier as display text.

    Falls back to de-underscoring rather than passing the raw token through, so
    a value type added later degrades to "a serial number" instead of leaking
    "serial_number" into the interface.
    """
    known = _VALUE_TYPE_LABELS.get(value_type)
    if known:
        return known
    words = value_type.replace("_", " ").strip()
    if not words:
        return "an unrecognised value"
    article = "an" if words[0] in "aeiou" else "a"
    return f"{article} {words}"


def classify_input(
    value: str,
    *,
    context: str | None = None,
) -> ClassificationResponse:
    """Classify a single input value and return ranked candidates.

    Stage A of the two-stage workflow: classify, then let the user confirm.
    Returns both document-type and value-type candidates.
    """
    from app.engines.card import mask_card_number
    from app.classification_store import store_classification

    candidates = classify_with_candidates(value.strip(), context=context, groq_client=get_groq_client())

    # Separate candidates by layer
    document_candidates = [c for c in candidates if c.layer == "document"]
    value_candidates = [c for c in candidates if c.layer == "value"]

    recommended_type = value_candidates[0].type if value_candidates else "unknown"
    recommended_label = value_candidates[0].label if value_candidates else "Unknown"
    top_document_type = document_candidates[0].type if document_candidates else "other"
    top_value_type = value_candidates[0].type if value_candidates else "unknown"

    display_value = value.strip()
    if recommended_type == "card_number" and len(display_value.replace(" ", "").replace("-", "")) >= 13:
        display_value = mask_card_number(display_value)
    elif recommended_type == "cnic":
        display_value = mask_cnic(display_value)

    # Store candidate types for the two-stage confirm flow
    all_candidate_types = list(dict.fromkeys(c.type for c in candidates))
    classification_id = store_classification(all_candidate_types)

    return ClassificationResponse(
        classification_id=classification_id,
        input_value=display_value,
        candidates=candidates,
        recommended_type=recommended_type,
        recommended_label=recommended_label,
        document_candidates=document_candidates,
        value_candidates=value_candidates,
        top_document_type=top_document_type,
        top_value_type=top_value_type,
    )


_AUTO_CLASSIFY_CONFIDENCE_THRESHOLD = 0.60


def analyze_single_value(
    value: str,
    *,
    confirmed_type: str | None = None,
    confirmed_document_type: str | None = None,
    confirmed_value_type: str | None = None,
) -> AnalysisResponse:
    """Analyze a single raw value (number, card number, date, etc.).

    If confirmed_value_type is provided, the user has explicitly selected a value-type
    classification and the system respects that choice instead of the automatic classification.

    If confirmed_document_type is provided, the user has explicitly selected a document-type
    classification (e.g., credit_card, debit_card, invoice).

    The legacy confirmed_type parameter is still supported for backward compatibility.

    When no confirmation is provided, the system uses the automatic classification only
    when confidence exceeds the threshold. Below the threshold, the result is
    insufficient_evidence rather than making an unsupported claim.
    """
    response = AnalysisResponse()
    is_confirmed = bool(confirmed_value_type or confirmed_type or confirmed_document_type)
    response.classification_source = "confirmed" if is_confirmed else "automatic"

    # When the caller already tells us the type (stage 2 of the two-stage flow, or a
    # direct confirmed_type call), skip re-classification entirely — it's wasted work
    # and, if confidence was low, an unnecessary Groq round trip. The confirmed type
    # is authoritative per spec: the user's choice overrides automatic detection.
    if is_confirmed:
        value_type = confirmed_value_type or confirmed_type
        response.input_classification = InputClassification(
            type=value_type or "unknown",
            confidence=1.0,
            evidence=["User-confirmed classification; automatic classification skipped."],
            candidates=[],
        )
        response.document_candidates = []
        response.value_candidates = []
        response.top_document_type = confirmed_document_type or ""
        response.top_value_type = value_type or ""
    else:
        candidates = classify_with_candidates(value.strip(), groq_client=get_groq_client())
        value_candidates = [c for c in candidates if c.layer == "value"]
        document_candidates = [c for c in candidates if c.layer == "document"]

        top_value = value_candidates[0] if value_candidates else None
        top_document = document_candidates[0] if document_candidates else None

        classification = InputClassification(
            type=top_value.type if top_value else "unknown",
            confidence=top_value.confidence if top_value else 0.3,
            evidence=[top_value.reason] if top_value and top_value.reason else [],
            candidates=candidates,
        )
        response.input_classification = classification

        response.document_candidates = document_candidates
        response.value_candidates = value_candidates
        response.top_document_type = top_document.type if top_document else ""
        response.top_value_type = top_value.type if top_value else ""

        if top_value and top_value.confidence >= _AUTO_CLASSIFY_CONFIDENCE_THRESHOLD:
            value_type = top_value.type
        else:
            value_type = None

    all_checks: list[Evidence] = []

    if confirmed_document_type:
        response.extracted_data["document_type"] = confirmed_document_type

    if value_type in ("card_number", "credit_card_candidate"):
        all_checks.extend(format_check(value))
        all_checks.append(degenerate_check(value))
        # Runs alongside degenerate_check rather than inside it: a placeholder
        # like 0000... is malformed, whereas a published test number is
        # perfectly well-formed and needs a different message and severity.
        all_checks.append(published_test_card_check(value))
        all_checks.append(luhn_check(value))
        all_checks.append(detect_network(value))
        response.extracted_data["masked_number"] = mask_card_number(value)

    elif value_type == "financial_amount":
        try:
            val = float(value.replace(",", "").replace("$", "").replace("€", "").replace("£", "").replace("₹", ""))
            response.extracted_data["value"] = val
            response.limitations = [
                "Single financial values cannot be assessed via Benford's Law.",
                "No fraud determination can be made from a single amount.",
            ]
            response.recommendation = "Provide a larger dataset for statistical analysis."
            response.overall_status = OverallStatus.INSUFFICIENT_EVIDENCE
        except ValueError:
            pass

    elif value_type == "date":
        response.extracted_data["raw"] = value
        all_checks.append(Evidence(
            check="date_format",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.PASSED,
            confidence=0.8,
            message="Value matches a date format.",
        ))
        response.limitations = ["Date validation is format-based only."]

    elif value_type == "cnic":
        all_checks.append(cnic_format_check(value))
        all_checks.append(cnic_province_check(value))
        all_checks.append(cnic_gender_digit_check(value))
        all_checks.append(cnic_degenerate_check(value))
        # Emitted last and always: it is the check that keeps a well-formed
        # CNIC from clearing the board and being reported as valid.
        all_checks.append(cnic_authority_note(value))
        response.extracted_data["masked_cnic"] = mask_cnic(value)
        response.extracted_data["formatted_cnic"] = format_cnic(value)
        for check in all_checks:
            if check.check == "cnic_region_code" and check.status == CheckStatus.PASSED:
                response.extracted_data["region"] = check.details.get("region")
            elif check.check == "cnic_gender_digit" and check.status == CheckStatus.PASSED:
                response.extracted_data["gender"] = check.details.get("gender")
        response.limitations = [
            "A CNIC carries no check digit, so structural checks cannot confirm "
            "that a well-formed number was ever issued.",
            "Confirming that this CNIC belongs to a real cardholder requires a "
            "record check against the issuing authority (NADRA).",
        ]

    elif value_type in ("identifier", "generic_identifier", "transaction_id", "invoice_reference", "invoice_number", "id_number", "passport_number", "license_number"):
        response.extracted_data["raw"] = value
        all_checks.append(Evidence(
            check="identifier_format",
            category=CheckCategory.FORMAT_VALIDATION,
            status=CheckStatus.UNKNOWN,
            confidence=0.4,
            message=(
                f"Value treated as {humanize_value_type(value_type)}. "
                "No specific validation rules are available for this type."
            ),
        ))
        response.limitations = ["Identifier verification requires an authoritative source."]

    else:
        response.extracted_data["raw"] = value
        if not is_confirmed:
            response.limitations = ["Could not determine what this value represents with sufficient confidence."]

    if all_checks:
        response.checks = all_checks
        response.risk_assessment = aggregate_evidence(all_checks)
        response.overall_status = determine_overall_status(
            response.risk_assessment, all_checks, response.limitations,
        )
        response.explanation = _build_explanation(response)
        groq_explanation = _groq_enhance_explanation(response)
        if groq_explanation:
            response.explanation = groq_explanation
    elif not response.explanation:
        response.explanation = _build_explanation(response)

    return response


def analyze_dataset(numbers: list[float], *, label: str = "Dataset") -> AnalysisResponse:
    """Analyze a list of numbers with Benford's Law + statistical checks."""
    response = AnalysisResponse()
    response.input_classification = InputClassification(
        type="financial_dataset",
        confidence=0.8,
        evidence=[f"{len(numbers)} numeric values provided"],
    )

    result: BenfordResult = benford_analyze(numbers)
    response.extracted_data = {
        "sample_size": result["total_count"],
        "invalid_values": result["invalid_count"],
    }

    response.statistical_analysis = {
        "benford": {
            "chi_square": result["chi_square"],
            "p_value": result.get("p_value"),
            "applicability": result.get("applicability", "unknown"),
            "sample_size_appropriate": result.get("sample_size_appropriate", False),
            "observed_frequencies": result["observed_frequencies"],
            "expected_frequencies": result["expected_frequencies"],
        },
    }

    two_digit_result = analyze_two_digit(numbers)
    response.statistical_analysis["benford_two_digit"] = {
        "chi_square": two_digit_result["chi_square"],
        "p_value": two_digit_result.get("p_value"),
        "applicability": two_digit_result.get("applicability", "unknown"),
        "observed_frequencies": two_digit_result["observed_frequencies"],
        "expected_frequencies": two_digit_result["expected_frequencies"],
    }

    all_checks: list[Evidence] = []
    applicability = result.get("applicability", "unknown")
    if applicability == "insufficient_data":
        all_checks.append(Evidence(
            check="benford_applicability",
            category=CheckCategory.STATISTICAL_ANALYSIS,
            status=CheckStatus.WARNING,
            confidence=0.9,
            severity=Severity.LOW,
            message=f"Sample size {result['total_count']} is too small for reliable Benford analysis (need 50+).",
        ))
        response.limitations.append("Sample size is too small for reliable Benford analysis.")
    elif applicability == "questionable":
        all_checks.append(Evidence(
            check="benford_applicability",
            category=CheckCategory.STATISTICAL_ANALYSIS,
            status=CheckStatus.WARNING,
            confidence=0.7,
            severity=Severity.LOW,
            message=f"Sample size {result['total_count']} is marginal for Benford analysis (100+ preferred).",
        ))

    chi_sq = result["chi_square"]
    valid_count = result["total_count"]
    if valid_count == 0:
        all_checks.append(Evidence(
            check="benford_chi_square",
            category=CheckCategory.STATISTICAL_ANALYSIS,
            status=CheckStatus.NOT_APPLICABLE,
            confidence=0.0,
            message="No valid numbers to evaluate chi-square.",
        ))
    elif chi_sq > 20.09:
        all_checks.append(Evidence(
            check="benford_chi_square",
            category=CheckCategory.STATISTICAL_ANALYSIS,
            status=CheckStatus.WARNING,
            confidence=0.8,
            severity=Severity.MEDIUM,
            message=f"Chi-square {chi_sq:.2f} exceeds p=0.01 critical value (20.09). Data deviates from Benford's Law.",
            details={"chi_square": chi_sq, "critical_001": 20.09},
        ))
    elif chi_sq > 15.51:
        all_checks.append(Evidence(
            check="benford_chi_square",
            category=CheckCategory.STATISTICAL_ANALYSIS,
            status=CheckStatus.WARNING,
            confidence=0.6,
            severity=Severity.LOW,
            message=f"Chi-square {chi_sq:.2f} exceeds p=0.05 critical value (15.51). Moderate deviation.",
            details={"chi_square": chi_sq, "critical_005": 15.51},
        ))
    else:
        all_checks.append(Evidence(
            check="benford_chi_square",
            category=CheckCategory.STATISTICAL_ANALYSIS,
            status=CheckStatus.PASSED,
            confidence=0.7,
            message=f"Chi-square {chi_sq:.2f} is within acceptable range.",
            details={"chi_square": chi_sq},
        ))

    two_digit_chi_sq = two_digit_result["chi_square"]
    if valid_count == 0:
        all_checks.append(Evidence(
            check="benford_two_digit_chi_square",
            category=CheckCategory.STATISTICAL_ANALYSIS,
            status=CheckStatus.NOT_APPLICABLE,
            confidence=0.0,
            message="No valid numbers to evaluate two-digit chi-square.",
        ))
    elif two_digit_chi_sq > 100.0:
        all_checks.append(Evidence(
            check="benford_two_digit_chi_square",
            category=CheckCategory.STATISTICAL_ANALYSIS,
            status=CheckStatus.WARNING,
            confidence=0.7,
            severity=Severity.MEDIUM,
            message=f"Two-digit chi-square {two_digit_chi_sq:.2f} is high. Significant deviation in first-two-digit distribution.",
            details={"chi_square": two_digit_chi_sq},
        ))
    else:
        all_checks.append(Evidence(
            check="benford_two_digit_chi_square",
            category=CheckCategory.STATISTICAL_ANALYSIS,
            status=CheckStatus.PASSED,
            confidence=0.6,
            message=f"Two-digit chi-square {two_digit_chi_sq:.2f} is within acceptable range.",
            details={"chi_square": two_digit_chi_sq},
        ))

    duplicates = _find_duplicates(numbers)
    if duplicates:
        all_checks.append(Evidence(
            check="duplicate_detection",
            category=CheckCategory.CONSISTENCY_CHECK,
            status=CheckStatus.WARNING,
            confidence=0.9,
            severity=Severity.LOW,
            message=f"Found {len(duplicates)} duplicate value(s).",
            details={"duplicates": duplicates[:10]},
        ))

    round_amounts = sum(1 for n in numbers if n != 0 and n % 100 == 0)
    if len(numbers) > 10 and round_amounts / len(numbers) > 0.5:
        all_checks.append(Evidence(
            check="round_amount_check",
            category=CheckCategory.STATISTICAL_ANALYSIS,
            status=CheckStatus.WARNING,
            confidence=0.6,
            severity=Severity.LOW,
            message=f"{round_amounts}/{len(numbers)} values are round (divisible by 100).",
        ))

    response.checks = all_checks
    response.risk_assessment = aggregate_evidence(all_checks)
    response.overall_status = determine_overall_status(
        response.risk_assessment, all_checks, response.limitations,
    )
    response.explanation = _build_explanation(response)
    groq_explanation = _groq_enhance_explanation(response)
    if groq_explanation:
        response.explanation = groq_explanation
    return response


def analyze_document_text(
    text: str,
    *,
    source_type: str = "document",
    readings: list[str] | None = None,
    exact: bool = False,
) -> AnalysisResponse:
    """Analyze text extracted from a document (OCR, PDF, etc.).

    `readings` carries the independent OCR passes over the same document, when
    the caller has them. Arithmetic verification uses them to tell a mismatch it
    can prove from one that might just be a misread. `exact` marks text that was
    never guessed at (a PDF's own text layer), where one reading is authoritative.
    """
    from app.ingestion.ocr_enhanced import extract_contextual_numbers, extract_dates

    response = AnalysisResponse()
    response.input_classification = InputClassification(
        type=source_type,
        confidence=0.7,
        evidence=[f"Text content from {source_type}"],
    )

    contextual = extract_contextual_numbers(text)
    all_numbers: list[float] = []
    for raw in contextual.get("all_numbers", []):
        cleaned = raw.replace(",", "").replace("$", "").replace("€", "").replace("£", "").replace("₹", "")
        try:
            all_numbers.append(float(cleaned))
        except ValueError:
            pass

    response.extracted_data = {
        "text_length": len(text),
        "numbers_found": len(all_numbers),
        "currency_amounts": contextual.get("currency_amounts", []),
        "labeled_amounts": contextual.get("labeled_amounts", []),
    }

    checks: list[Evidence] = []

    # Arithmetic verification runs first because its outcome decides whether the
    # statistical test below is meaningful at all. An invoice or statement is
    # internally checkable regardless of how few numbers it has, which is what
    # makes it useful here — a single document can never reach Benford's
    # 50-value minimum.
    invoice_fields = extract_invoice_fields(readings or [text], exact=exact)
    arithmetic_checks = verify_extracted_document(invoice_fields)
    if arithmetic_checks:
        checks.extend(arithmetic_checks)
        response.consistency_analysis = {
            "extracted_fields": {
                name: {"value": f.value, "agreement": round(f.agreement, 4)}
                for name, f in invoice_fields.fields.items()
            },
            "readings_compared": len(readings or [text]),
            "source_is_exact": exact,
        }

    document_kind = invoice_fields.document_kind()

    if document_kind:
        # The page states figures that verify against each other, which is what
        # it means to be an invoice or a statement. Record that as the document
        # type: leaving it unset let the client fall back to its own default and
        # announce a scanned invoice as an "ID Number".
        label = "Invoice" if document_kind == "invoice" else "Bank statement"
        response.top_document_type = document_kind
        response.document_candidates = [ClassificationCandidate(
            type=document_kind,
            label=label,
            confidence=0.95,
            reason="Document states a subtotal and total that verify arithmetically."
            if document_kind == "invoice"
            else "Document states opening and closing balances that reconcile.",
            layer="document",
        )]
        response.input_classification = InputClassification(
            type=document_kind,
            confidence=0.95,
            evidence=[f"{label} structure detected: " + ", ".join(sorted(invoice_fields.fields))],
        )

    if document_kind:
        # Benford's Law describes datasets of naturally-occurring values spanning
        # orders of magnitude. The numbers on one invoice are zip codes, dates, a
        # P.O. number and a few quantities — a mixed bag from a single page, not
        # such a dataset. Running the chi-square over them yields a number with
        # no meaning, and because a mixed bag rarely fits the curve, that number
        # reads as "anomalous" on documents whose own arithmetic proves them
        # correct. Recorded as not-applicable rather than skipped in silence: a
        # reader of the report should see that the test was considered and why it
        # was set aside, and a not-applicable check carries no risk weight.
        checks.append(Evidence(
            check="benford_applicability",
            category=CheckCategory.STATISTICAL_ANALYSIS,
            status=CheckStatus.NOT_APPLICABLE,
            confidence=1.0,
            severity=Severity.NONE,
            message=(
                f"Benford's Law analysis does not apply to a single invoice or "
                f"statement. The {len(all_numbers)} numbers on this document are "
                f"identifiers, dates and quantities rather than a dataset of "
                f"comparable values, so a digit-distribution test over them would "
                f"not be meaningful. This document was verified by arithmetic "
                f"instead, which is conclusive where Benford's Law is not."
            ),
            details={
                "numbers_on_document": len(all_numbers),
                "reason": "single_document_not_a_dataset",
                "verified_by": "arithmetic_consistency",
            },
        ))
    elif len(all_numbers) >= 50:
        benford_resp = analyze_dataset(all_numbers)
        checks.extend(benford_resp.checks)
        response.statistical_analysis = benford_resp.statistical_analysis
        response.limitations.extend(benford_resp.limitations)
    elif all_numbers:
        checks.append(Evidence(
            check="sample_size",
            category=CheckCategory.STATISTICAL_ANALYSIS,
            status=CheckStatus.WARNING,
            confidence=0.9,
            message=f"Only {len(all_numbers)} numbers extracted — insufficient for Benford analysis.",
        ))
        response.limitations.append("Too few numbers for Benford analysis.")

    if source_type == "cv" or source_type == "resume":
        checks.extend(analyze_cv(text))

    dates = extract_dates(text)
    if dates:
        response.extracted_data["dates"] = dates

    response.checks = checks
    if checks:
        response.risk_assessment = aggregate_evidence(checks)
        response.overall_status = determine_overall_status(
            response.risk_assessment, checks, response.limitations,
        )
    response.explanation = _build_explanation(response)
    groq_explanation = _groq_enhance_explanation(response)
    if groq_explanation:
        response.explanation = groq_explanation
    return response


def analyze_file(
    file_path: str,
    *,
    declared_type: str = "auto",
    prior_vision: "VisionClassification | None" = None,
) -> AnalysisResponse:
    """Analyze an uploaded file (image, PDF, CSV, XLSX).

    `prior_vision` lets a caller supply a document classification it already
    obtained, so an image is not sent to the vision model a second time for an
    answer that is already known.
    """
    path = Path(file_path)
    if not path.exists():
        resp = AnalysisResponse()
        resp.overall_status = OverallStatus.INVALID
        resp.limitations = ["File not found."]
        return resp

    suffix = path.suffix.lower()

    if suffix in (".csv",):
        return _analyze_csv(file_path)
    elif suffix in (".xlsx", ".xls"):
        return _analyze_xlsx(file_path)
    elif suffix == ".pdf":
        return _analyze_pdf(file_path)
    elif suffix in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"):
        return _analyze_image(file_path, prior_vision)
    else:
        resp = AnalysisResponse()
        resp.overall_status = OverallStatus.INVALID
        resp.limitations = [f"Unsupported file type: {suffix}"]
        return resp


def _analyze_csv(file_path: str) -> AnalysisResponse:
    from app.ingestion.csv_xlsx import detect_numeric_columns, identify_date_columns, read_csv

    headers, rows = read_csv(file_path)
    if not headers:
        resp = AnalysisResponse()
        resp.overall_status = OverallStatus.INVALID
        resp.limitations = ["CSV file is empty."]
        return resp

    numeric_cols = detect_numeric_columns(headers, rows)
    date_cols = identify_date_columns(headers, rows)

    candidate_cols = {k: v for k, v in numeric_cols.items() if k not in date_cols}

    if not candidate_cols:
        resp = AnalysisResponse()
        resp.input_classification = InputClassification(type="csv", confidence=0.9, evidence=["CSV with headers"])
        resp.limitations = ["No numerical columns suitable for Benford analysis."]
        resp.overall_status = OverallStatus.INSUFFICIENT_EVIDENCE
        return resp

    best_col = max(candidate_cols, key=lambda k: len(candidate_cols[k]))
    response = analyze_dataset(candidate_cols[best_col], label=f"Column: {best_col}")
    _flag_other_numeric_columns(response, candidate_cols, best_col)
    return response


def _analyze_xlsx(file_path: str) -> AnalysisResponse:
    from app.ingestion.csv_xlsx import detect_numeric_columns, identify_date_columns, read_xlsx

    try:
        headers, rows = read_xlsx(file_path)
    except FileNotFoundError as exc:
        resp = AnalysisResponse()
        resp.overall_status = OverallStatus.INVALID
        resp.limitations = [str(exc)]
        return resp

    if not headers:
        resp = AnalysisResponse()
        resp.overall_status = OverallStatus.INVALID
        resp.limitations = ["XLSX file is empty."]
        return resp

    numeric_cols = detect_numeric_columns(headers, rows)
    date_cols = identify_date_columns(headers, rows)
    candidate_cols = {k: v for k, v in numeric_cols.items() if k not in date_cols}

    if not candidate_cols:
        resp = AnalysisResponse()
        resp.input_classification = InputClassification(type="xlsx", confidence=0.9, evidence=["XLSX with headers"])
        resp.limitations = ["No numerical columns suitable for Benford analysis."]
        resp.overall_status = OverallStatus.INSUFFICIENT_EVIDENCE
        return resp

    best_col = max(candidate_cols, key=lambda k: len(candidate_cols[k]))
    response = analyze_dataset(candidate_cols[best_col], label=f"Column: {best_col}")
    _flag_other_numeric_columns(response, candidate_cols, best_col)
    return response


_OTHER_COLUMN_MIN_SAMPLE = 50


def _flag_other_numeric_columns(
    response: AnalysisResponse,
    candidate_cols: dict[str, list[float]],
    primary_col: str,
) -> None:
    """CSV/XLSX analysis only runs Benford's Law on the single largest numeric
    column above. Fabricated data confined to a smaller column would otherwise
    be invisible — flag any other column that also has enough samples and
    deviates significantly, without changing the primary result's shape."""
    flags: list[tuple[str, float, int]] = []
    for col, values in candidate_cols.items():
        if col == primary_col or len(values) < _OTHER_COLUMN_MIN_SAMPLE:
            continue
        result = benford_analyze(values)
        if result.get("applicability") == "insufficient_data":
            continue
        chi_sq = result["chi_square"]
        if chi_sq > 20.09:
            flags.append((col, chi_sq, len(values)))

    if not flags:
        return

    response.limitations.append(
        "Additional numeric column(s) also show statistical anomalies: "
        + ", ".join(f"'{c}'" for c, _, _ in flags) + "."
    )
    _append_checks(response, [
        Evidence(
            check="benford_chi_square_secondary_column",
            category=CheckCategory.STATISTICAL_ANALYSIS,
            status=CheckStatus.WARNING,
            confidence=0.7,
            severity=Severity.MEDIUM,
            message=(
                f"Column '{col}' ({n} values) also deviates from Benford's Law "
                f"(chi-square {chi_sq:.2f}) but was not the primary analyzed column."
            ),
            details={"column": col, "chi_square": chi_sq},
        )
        for col, chi_sq, n in flags
    ])


def _append_checks(response: AnalysisResponse, checks: list[Evidence]) -> None:
    """Add evidence to a finished response and re-derive its verdict.

    Appending to `response.checks` alone would leave the risk score and overall
    status describing the analysis as it stood before the new evidence arrived.
    """
    if not checks:
        return
    response.checks.extend(checks)
    response.risk_assessment = aggregate_evidence(response.checks)
    response.overall_status = determine_overall_status(
        response.risk_assessment, response.checks, response.limitations,
    )
    response.explanation = _build_explanation(response)
    groq_explanation = _groq_enhance_explanation(response)
    if groq_explanation:
        response.explanation = groq_explanation


def _analyze_pdf(file_path: str) -> AnalysisResponse:
    # Imported as a module rather than a name so the extractor stays patchable
    # and so `exact` always travels with the text it describes.
    from app.ingestion import pdf as pdf_ingestion

    try:
        text, exact = pdf_ingestion.extract_text_from_pdf(file_path)
    except Exception as exc:
        resp = AnalysisResponse()
        resp.overall_status = OverallStatus.INVALID
        resp.limitations = [f"PDF extraction failed: {exc}"]
        return resp

    if not text.strip():
        resp = AnalysisResponse()
        resp.overall_status = OverallStatus.INVALID
        resp.limitations = [
            "Could not extract text from PDF.",
            "Install pymupdf for PDF text extraction: pip install pymupdf",
        ]
        return resp

    response = analyze_document_text(text, source_type="pdf", exact=exact)

    # A PDF is the one input where the line items themselves are legible as a
    # table, so it is the one input where a padded middle can be caught rather
    # than only a contradictory bottom.
    try:
        tables = pdf_ingestion.extract_tables_from_pdf(file_path)
    except Exception:
        tables = []
    if tables:
        line_item_checks = verify_line_items(
            tables,
            stated_subtotal=extract_invoice_fields([text], exact=exact).value_of("subtotal"),
        )
        if line_item_checks:
            _append_checks(response, line_item_checks)

    return response


def _apply_ocr_validation(resp: AnalysisResponse, candidate: "OcrCardCandidate") -> None:
    """Apply OCR-specific validation to prevent false-positive card verification.

    Luhn is a checksum, not proof that OCR extracted the correct number.
    For OCR-derived candidates, an unknown network is treated as uncertainty,
    and the verdict is downgraded accordingly.
    """
    limitations: list[str] = list(resp.limitations) if resp.limitations else []
    num_digits = len(candidate.digits)

    if not candidate.network:
        limitations.append(
            f"OCR-extracted {num_digits}-digit number does not match "
            f"any recognized card network."
        )

    consensus_ratio = (
        candidate.variant_agreement / candidate.total_variants
        if candidate.total_variants > 0 else 0.0
    )
    low_consensus = consensus_ratio < 0.3
    if low_consensus:
        limitations.append(
            "Low OCR variant agreement — the extracted number may be inaccurate."
        )

    if not candidate.network:
        if resp.overall_status == OverallStatus.LIKELY_VALID:
            resp.overall_status = OverallStatus.INSUFFICIENT_EVIDENCE
            limitations.append(
                "OCR-extracted number passed Luhn checksum but does not match "
                "any known card network. This may be a coincidental Luhn match "
                "on incorrectly extracted digits."
            )

    # Even when the network matches, a low-consensus reading is not trustworthy —
    # different OCR variants disagreeing on the digits means a Luhn/network match
    # on the winning candidate could still be coincidental. Without this, a badly
    # OCR'd number that happens to look valid would report LIKELY_VALID despite
    # the limitation text above, silently letting a misread pass as verified.
    if low_consensus and resp.overall_status == OverallStatus.LIKELY_VALID:
        resp.overall_status = OverallStatus.INSUFFICIENT_EVIDENCE
        limitations.append(
            "OCR variant agreement was too low to trust this reading, even though "
            "it passed Luhn and matched a known network."
        )

    resp.limitations = limitations


def _should_treat_as_card(
    candidate: "OcrCardCandidate", *, has_document_structure: bool
) -> bool:
    """Whether a digit run found by OCR may claim the whole document.

    Two independent tests say whether something is card-shaped: the Luhn
    checksum, and whether its opening digits match a real card network. A run
    failing *both* has nothing left arguing for it — and long runs of unrelated
    digits are exactly what a page produces, because OCR happily concatenates a
    phone number printed twice into nineteen digits. Those are rejected here so
    the page is read as a document instead.

    Passing either test keeps the card path: a real card whose network lookup
    failed still deserves the card checks, and _apply_ocr_validation downgrades
    the verdict afterwards rather than the routing discarding it.

    A page that verifies its own arithmetic outranks any of this: an invoice is
    an invoice however card-shaped some number printed on it happens to be.
    """
    if has_document_structure:
        return False
    return bool(candidate.network) or candidate.luhn_valid


_CARD_DOCUMENT_TYPES = frozenset({"credit_card", "debit_card"})


def _needs_digit_line_rescan(
    vision: "VisionClassification | None", has_structure: bool
) -> bool:
    """Whether the targeted card-number re-read is worth its cost on this image.

    The rescan crops each digit-rich line and re-reads it at 3x under both
    polarities with the alphabet restricted to 0-9. That is what makes embossed
    or stylised card type readable, and it is the most expensive step in an
    image upload — 9-13s on the invoice fixtures, on pages that have no card
    number to find.

    Skipped only on positive evidence that the page is something else: it
    states figures that verify against each other, or the vision model
    confidently named a non-card document. Absence of evidence is not enough —
    when vision is unconfigured or fails, the rescan still runs, because that is
    exactly the situation the deterministic path has to cover alone.
    """
    if has_structure:
        return False
    if (
        vision is not None
        and vision.confidence >= 0.70
        and vision.value_type != "card_number"
        and vision.document_type not in _CARD_DOCUMENT_TYPES
    ):
        return False
    return True


def _analyze_image(
    file_path: str, prior_vision: "VisionClassification | None" = None
) -> AnalysisResponse:
    try:
        from app.ocr import (
            OcrCardCandidate,
            extract_best_card_candidate,
            extract_text_readings,
        )
    except SystemExit:
        resp = AnalysisResponse()
        resp.overall_status = OverallStatus.INVALID
        resp.limitations = ["OCR dependencies not available."]
        return resp

    # Read the page once, up front, and let both paths share the result.
    #
    # This used to start with the card extraction, which ran its own full sweep
    # of the preprocessing variants plus the digit-line rescan before anything
    # had established what the image was. An invoice therefore paid for a
    # complete card extraction it could never benefit from — measured at 12-16s
    # of a 24-32s upload on the two invoice fixtures — and then paid again for
    # the document sweep below, because the card sweep's text was discarded.
    #
    # A corrupt/truncated file or a non-image file uploaded with an image
    # extension raises from PIL (e.g. UnidentifiedImageError), not SystemExit.
    # Without this, such uploads would 500 instead of returning a normal
    # analysis response like every other malformed-input path in this module.
    try:
        document_readings = extract_text_readings(file_path)
    except SystemExit:
        resp = AnalysisResponse()
        resp.overall_status = OverallStatus.INVALID
        resp.limitations = ["OCR dependencies not available."]
        return resp
    except Exception as exc:
        resp = AnalysisResponse()
        resp.overall_status = OverallStatus.INVALID
        resp.limitations = [f"Could not read image file: {exc}"]
        return resp

    # Whether the page verifies its own arithmetic. Known before the card
    # pipeline runs, which is what lets the expensive part of it be skipped.
    has_structure = bool(
        document_readings
        and extract_invoice_fields(document_readings).has_document_structure()
    )

    # What the document looks like, independent of what OCR could read: a card
    # whose digits scan badly is still recognisably a card by its layout and
    # network mark. The caller may already have this — the client asks for it up
    # front to narrate the processing screen — in which case reuse it rather than
    # paying for the identical classification twice.
    #
    # Asked before the card extraction rather than after, because its answer
    # decides whether the expensive half of that extraction is worth running.
    vision = prior_vision if prior_vision is not None else _classify_image_with_vision(file_path)

    try:
        card_candidate = extract_best_card_candidate(
            file_path,
            readings=document_readings,
            digit_line_rescan=_needs_digit_line_rescan(vision, has_structure),
        )
    except SystemExit:
        resp = AnalysisResponse()
        resp.overall_status = OverallStatus.INVALID
        resp.limitations = ["OCR dependencies not available."]
        return resp
    except Exception as exc:
        resp = AnalysisResponse()
        resp.overall_status = OverallStatus.INVALID
        resp.limitations = [f"Could not read image file: {exc}"]
        return resp

    # Vision is the intended guard against OCR's implicit "digits found,
    # therefore a card" assumption, but it is an optional external service: when
    # it is unconfigured or failing, that guard silently disappears and any page
    # with enough digits on it gets analysed as a card number. So check the page
    # itself as well.
    #
    # Only weak candidates are worth this second look. A digit run matching a
    # real card network is card-shaped on its own evidence and keeps the fast
    # path; one matching no network is exactly what a page of unrelated numbers
    # produces — a street number, a P.O. number and a year, run together into
    # something that passes Luhn by coincidence.
    if card_candidate and not card_candidate.network:
        if not _should_treat_as_card(card_candidate, has_document_structure=has_structure):
            card_candidate = None

    if card_candidate:
        value_type = "card_number"
        if vision and vision.confidence >= 0.70 and vision.value_type != "card_number":
            value_type = vision.value_type

        resp = analyze_single_value(card_candidate.digits, confirmed_value_type=value_type)
        resp.extracted_data["ocr_card_candidate"] = card_candidate.digits
        resp.extracted_data["source"] = "image_ocr"
        resp.classification_source = "automatic"
        _record_vision_classification(resp, vision)

        if value_type == "card_number":
            _apply_ocr_validation(resp, card_candidate)

        return resp

    # Vision confidently identified this as a card, but OCR found no digit run
    # worth trusting. Falling through to generic document analysis would bury
    # that verdict: the card face gets treated as an arbitrary set of numbers
    # and run through Benford's law, which is meaningless here and surfaces a
    # misleading "too few numbers" note instead of a verdict on the card.
    #
    # So ask the vision model to read the number instead. Tesseract's ceiling on
    # embossed card type is the whole reason this path is reached, and a
    # multimodal model reads that type directly. A page with genuine
    # invoice/table structure is stronger, more specific evidence than a generic
    # vision guess and keeps the document path below.
    if (
        vision
        and vision.confidence >= 0.70
        and vision.value_type == "card_number"
        and not has_structure
    ):
        transcribed = _transcribe_card_with_vision(file_path)
        if transcribed:
            resp = analyze_single_value(transcribed, confirmed_value_type="card_number")
            resp.extracted_data["ocr_card_candidate"] = transcribed
            resp.extracted_data["source"] = "vision_transcription"
            resp.classification_source = "automatic"
            _record_vision_classification(resp, vision)
            # Recorded so a reader can weigh the verdict: these digits were read
            # by a model, not by the deterministic OCR path, and no second pass
            # corroborated them.
            resp.limitations = list(resp.limitations) + [
                "Card number was read by the vision model because OCR could not "
                "extract it reliably; the digits themselves are uncorroborated."
            ]
            return resp

        resp = AnalysisResponse()
        resp.overall_status = OverallStatus.INSUFFICIENT_EVIDENCE
        resp.limitations = [
            "Image recognized as a credit/debit card, but the card number "
            "could not be read from it."
        ]
        _record_vision_classification(resp, vision)
        return resp

    # Multiple independently preprocessed passes, kept separate: arithmetic
    # verification needs to know whether they agreed, not just what they said.
    # Swept once at the top of this function and shared with the card path.
    readings = document_readings
    text = "\n".join(readings)

    if not text.strip():
        # OCR found nothing, but vision may still recognise the document from its
        # appearance alone — a photo too blurry to read can remain obviously a
        # passport. Report that instead of giving up entirely.
        if vision:
            resp = AnalysisResponse()
            resp.overall_status = OverallStatus.INSUFFICIENT_EVIDENCE
            resp.limitations = [
                "No text detected in image; document type identified visually only."
            ]
            _record_vision_classification(resp, vision)
            return resp

        resp = AnalysisResponse()
        resp.overall_status = OverallStatus.INSUFFICIENT_EVIDENCE
        resp.limitations = ["No text detected in image."]
        return resp

    resp = analyze_document_text(text, source_type="image_ocr", readings=readings)
    _record_vision_classification(resp, vision)
    return resp


def _classify_image_with_vision(file_path: str) -> "VisionClassification | None":
    """Run vision classification, never letting its failure break the upload."""
    try:
        from app.engines.classifier import classify_image_document

        return classify_image_document(file_path)
    except Exception:
        return None


def _transcribe_card_with_vision(file_path: str) -> str | None:
    """Read a card number with the vision model, never letting failure break the upload."""
    try:
        from app.engines.classifier import transcribe_card_number

        return transcribe_card_number(file_path)
    except Exception:
        return None


def _record_vision_classification(
    resp: AnalysisResponse, vision: "VisionClassification | None"
) -> None:
    """Attach the vision verdict to the response for display and audit.

    Recorded as supporting evidence rather than as the fraud verdict — the model
    identifies what a document *is*, never whether it is genuine.
    """
    if vision is None:
        return

    resp.extracted_data["vision_document_type"] = vision.document_type
    resp.extracted_data["vision_value_type"] = vision.value_type
    resp.extracted_data["vision_confidence"] = round(vision.confidence, 4)
    resp.extracted_data["vision_reason"] = vision.reason

    if resp.input_classification is None:
        resp.input_classification = InputClassification(
            type=vision.value_type,
            confidence=vision.confidence,
            evidence=[f"Vision: {vision.reason}"],
        )
    else:
        resp.input_classification.evidence.append(
            f"Vision: {vision.document_type} ({vision.confidence:.0%}) — {vision.reason}"
        )


def _find_duplicates(numbers: list[float]) -> list[float]:
    seen: dict[float, int] = {}
    dupes: list[float] = []
    for n in numbers:
        count = seen.get(n, 0) + 1
        seen[n] = count
        if count == 2:
            dupes.append(n)
    return dupes


def _build_explanation(response: AnalysisResponse) -> str:
    parts: list[str] = []
    if response.input_classification:
        # humanize_value_type, not the raw identifier. This field is not
        # rendered by the current UI, but it is part of the public API response
        # and was the last place the internal vocabulary escaped as prose.
        parts.append(
            f"Input classified as {humanize_value_type(response.input_classification.type)} "
            f"(confidence: {response.input_classification.confidence:.0%})."
        )
    passed = sum(1 for c in response.checks if c.status == CheckStatus.PASSED)
    failed = sum(1 for c in response.checks if c.status == CheckStatus.FAILED)
    warned = sum(1 for c in response.checks if c.status == CheckStatus.WARNING)
    parts.append(f"Checks: {passed} passed, {warned} warnings, {failed} failed out of {len(response.checks)}.")
    if response.risk_assessment:
        parts.append(f"Risk: {response.risk_assessment.risk_score}/100 ({response.risk_assessment.level}).")
    if response.limitations:
        parts.append("Limitations: " + "; ".join(response.limitations) + ".")
    return " ".join(parts)


def _groq_enhance_explanation(response: AnalysisResponse) -> str | None:
    """Use Groq to generate a contextual explanation of analysis results. Returns None on failure."""
    client = get_groq_client()
    if not client.available:
        return None

    checks_summary = "\n".join(
        f"- {c.check}: {c.status.value} ({c.confidence:.0%}) — {c.message}"
        for c in response.checks
    )
    risk = f"{response.risk_assessment.risk_score}/100 ({response.risk_assessment.level})" if response.risk_assessment else "N/A"
    stat_summary = ""
    if response.statistical_analysis:
        benford = response.statistical_analysis.get("benford")
        if isinstance(benford, dict):
            stat_summary = (
                f"Benford chi-square: {benford.get('chi_square', 'N/A')}, "
                f"p-value: {benford.get('p_value', 'N/A')}, "
                f"applicability: {benford.get('applicability', 'N/A')}"
            )
        two_digit = response.statistical_analysis.get("benford_two_digit")
        if isinstance(two_digit, dict):
            stat_summary += (
                f"\nTwo-digit Benford chi-square: {two_digit.get('chi_square', 'N/A')}, "
                f"applicability: {two_digit.get('applicability', 'N/A')}"
            )

    system_prompt = (
        "You are a financial fraud analyst. A verification pipeline has analysed some data. "
        "Provide a concise 2-4 sentence summary interpreting the results. "
        "Focus on what the evidence means, not how the system works. Be direct and professional."
    )
    user_content = (
        f"Classification: {response.input_classification.type if response.input_classification else 'N/A'}\n"
        f"Overall status: {response.overall_status.value}\n"
        f"Risk: {risk}\n"
        f"Statistical analysis:\n{stat_summary}\n"
        f"Checks performed:\n{checks_summary}\n"
        f"Limitations: {'; '.join(response.limitations) or 'None'}"
    )

    try:
        return client.chat(system_prompt, user_content, max_tokens=256)
    except Exception:
        return None
