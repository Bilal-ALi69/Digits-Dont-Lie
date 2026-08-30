"""CV / Resume analysis: extraction and internal consistency checks."""

from __future__ import annotations

import re

from app.models import Evidence, CheckCategory, CheckStatus, Severity


def extract_cv_sections(text: str) -> dict[str, list[str]]:
    """Extract basic sections from CV text using heuristics."""
    sections: dict[str, list[str]] = {
        "employment": [],
        "education": [],
        "skills": [],
        "dates": [],
        "names": [],
    }
    lines = text.split("\n")
    current_section = "general"
    section_patterns = {
        "employment": re.compile(r"(experience|employment|work\s*history|career)", re.I),
        "education": re.compile(r"(education|academic|qualifications|degree)", re.I),
        "skills": re.compile(r"(skills|competencies|technologies|proficiencies)", re.I),
    }
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        for sect, pat in section_patterns.items():
            if pat.search(stripped):
                current_section = sect
                break
        else:
            if current_section in sections:
                sections[current_section].append(stripped)

    date_pattern = re.compile(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b"
        r"|\b\d{4}\s*[-–]\s*(?:Present|Current|\d{4})\b"
        r"|\b\d{1,2}/\d{4}\s*[-–]\s*(?:Present|Current|\d{1,2}/\d{4})\b",
        re.I,
    )
    for line in lines:
        matches = date_pattern.findall(line)
        sections["dates"].extend(matches)

    return sections


def check_date_overlaps(dates: list[str]) -> list[Evidence]:
    """Flag potential date overlaps or inconsistencies."""
    results: list[Evidence] = []
    if len(dates) < 2:
        return results

    results.append(Evidence(
        check="cv_date_extraction",
        category=CheckCategory.CONSISTENCY_CHECK,
        status=CheckStatus.PASSED,
        confidence=0.7,
        message=f"Extracted {len(dates)} date references from the document.",
        details={"dates_found": len(dates)},
    ))

    results.append(Evidence(
        check="cv_date_overlap_analysis",
        category=CheckCategory.CONSISTENCY_CHECK,
        status=CheckStatus.REQUIRES_REVIEW,
        confidence=0.5,
        message="Automated date overlap analysis requires structured date parsing. Manual review recommended.",
    ))

    return results


def analyze_cv(text: str) -> list[Evidence]:
    """Run CV/resume analysis."""
    results: list[Evidence] = []
    sections = extract_cv_sections(text)

    has_employment = len(sections.get("employment", [])) > 0
    has_education = len(sections.get("education", [])) > 0
    has_skills = len(sections.get("skills", [])) > 0
    has_dates = len(sections.get("dates", [])) > 0

    results.append(Evidence(
        check="cv_structure",
        category=CheckCategory.STRUCTURAL_VALIDATION,
        status=CheckStatus.PASSED if (has_employment or has_education) else CheckStatus.WARNING,
        confidence=0.6,
        message=(
            "Document contains employment and/or education sections."
            if (has_employment or has_education)
            else "Could not identify standard CV sections."
        ),
        details={
            "has_employment": has_employment,
            "has_education": has_education,
            "has_skills": has_skills,
            "has_dates": has_dates,
        },
    ))

    if has_dates:
        results.extend(check_date_overlaps(sections["dates"]))

    return results
