"""Fairset human-facing report table — mirrors FairsetReview ``scripts/generate_report.py``."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

# Columns shown in FairsetReview Streamlit table / Excel export (after filtering failures).
FAIRSET_REVIEW_DISPLAY_COLUMNS: tuple[str, ...] = (
    "Logic Type",
    "Description",
    "Columns",
    "Percentage of rows impacted",
    "Number of impacted rows",
    "Wrong rows's index",
    "Supported",
)


def convert_logic_type(label: Any) -> str:
    """Same mapping as FairsetReview ``scripts/generate_report.convert_type``."""
    s = label if isinstance(label, str) else ("" if label is None else str(label))
    if s.startswith("Block"):
        parts = s.split(" ")
        if "Multi-to-Single" in parts:
            s = "Compound Skip Logic"
        elif "Multi-to-Multi" in parts:
            s = "Piping"
        else:
            s = "Skip Logic"
    elif s.startswith("Force"):
        s = "Mandatory Logic"
    elif s.startswith("Recoding"):
        s = "Recoding"

    translation = {
        "Block": "Skip Logic",
        "Force": "Mandatory Logic",
        "Compound Skip Logic": "Compound Skip Logic",
        "Piping": "Piping",
        "Sum": "Calculation Logic",
        "Recoding": "Recodes/Hidden Variables",
        "None of the Above": "Exclusive",
        "All of the Above": "Exclusive",
        "Count": "Selection Limit Control",
        "Uniqueness": "Ranking",
    }
    return translation.get(s, s)


def _merged_detail_description(item: dict[str, Any]) -> str:
    """Mirrors FairsetReview ``readOuput`` Detail merge."""
    if item.get("Detail"):
        return str(item["Detail"])
    return str(item.get("Description", "") or "")


def _failure_items(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only ``is_valid is False``, same filter as FairsetReview ``readOuput``."""
    out: list[dict[str, Any]] = []
    for item in report:
        if not isinstance(item, dict) or not item:
            continue
        if item.get("is_valid") is not False:
            continue
        merged = {**item, "Detail": _merged_detail_description(item)}
        out.append(merged)
    return out


def _columns_from_dataframe_cell(dataframe_field: Any) -> str:
    if dataframe_field is None:
        return ""
    try:
        cols = pd.DataFrame(dataframe_field).columns
        return ", ".join(map(str, cols))
    except Exception:
        return ""


def fairset_review_report_dataframe(report: list[dict[str, Any]]) -> pd.DataFrame:
    """Build the same dataframe FairsetReview builds before CSV/Excel export."""
    failures = _failure_items(report)
    if not failures:
        return pd.DataFrame(columns=list(FAIRSET_REVIEW_DISPLAY_COLUMNS))

    rows_norm = [
        {
            "Type": item.get("Type"),
            "is_supported": item.get("is_supported"),
            "Dataframe": item.get("Dataframe"),
            "Detail": item.get("Detail"),
            "Percentage_of_valid_rows": item.get("Percentage_of_valid_rows"),
            "Rows": item.get("Rows") if isinstance(item.get("Rows"), list) else [],
        }
        for item in failures
    ]
    df = pd.DataFrame(rows_norm)

    df["Logic Type"] = df["Type"].apply(convert_logic_type)

    df["Percentage of rows impacted"] = df["Percentage_of_valid_rows"].apply(
        lambda x: round(100 - float(x), 2) if pd.notna(x) else ""
    )

    df["Number of impacted rows"] = df["Rows"].apply(lambda x: len(x) if isinstance(x, list) else 0)

    df["Wrong rows's index"] = df["Rows"].astype(str).str.replace(r"[\[\]]", "", regex=True)

    df["Description"] = df.apply(
        lambda row: (
            "Selecting one answer prevents the selection of any other options."
            if row["Logic Type"] == "Exclusive"
            else (
                "Minimum and/or maximum limits on the number of choices a respondent can select."
                if row["Logic Type"] == "Selection Limit Control"
                else (
                    "Dynamic answer choices"
                    if row["Logic Type"] == "Dynamic Piping Single-to-Single"
                    else (str(row["Detail"]) if pd.notna(row["Detail"]) and str(row["Detail"]).strip() != "" else "")
                )
            )
        ),
        axis=1,
    )

    df["Columns"] = df["Dataframe"].apply(_columns_from_dataframe_cell)

    df["Supported"] = df["is_supported"].apply(lambda x: "No" if x is False else "Yes")

    return df[list(FAIRSET_REVIEW_DISPLAY_COLUMNS)]


def affected_row_index_count(display_df: pd.DataFrame) -> int:
    """Unique integers extracted from ``Wrong rows's index`` (FairsetReview Excel summary)."""
    all_indexes: set[int] = set()
    if display_df.empty or "Wrong rows's index" not in display_df.columns:
        return 0
    for val in display_df["Wrong rows's index"]:
        numbers = re.findall(r"\d+", str(val))
        all_indexes.update(map(int, numbers))
    return len(all_indexes)
