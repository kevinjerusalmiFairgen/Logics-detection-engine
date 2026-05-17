"""CSV serialization aligned with FairsetReview ``scripts/generate_report`` tabular export."""

from __future__ import annotations

from typing import Any

from logic_platform.fairset.report_table import fairset_review_report_dataframe


def fairset_report_to_csv(report: list[dict[str, Any]]) -> str:
    """Failures-only table with FairsetReview column names (matches Streamlit / Excel export)."""
    df = fairset_review_report_dataframe(report)
    return df.to_csv(index=False)
