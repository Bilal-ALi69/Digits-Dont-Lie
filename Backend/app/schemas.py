"""Pydantic request/response models for the API."""

from typing import Dict, List

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    """Body of a POST /analyze request: the raw list of numbers to test."""

    numbers: List[float] = Field(
        ...,
        description="List of numeric values to analyse for Benford conformance.",
    )


class AnalyzeResponse(BaseModel):
    """Result of a Benford analysis on a set of numbers."""

    total_count: int = Field(..., description="Number of valid values analysed (N).")
    invalid_count: int = Field(
        ..., description="Number of input values rejected by preprocessing."
    )
    observed_counts: Dict[str, int] = Field(
        ..., description="Observed count of each leading digit 1..9."
    )
    observed_frequencies: Dict[str, float] = Field(
        ..., description="Observed frequency (percentage) of each leading digit."
    )
    expected_frequencies: Dict[str, float] = Field(
        ..., description="Benford's Law expected frequency (percentage) per digit."
    )
    chi_square: float = Field(..., description="Chi-Square goodness-of-fit statistic.")
