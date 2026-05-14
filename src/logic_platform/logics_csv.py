"""Utilities for reading and normalizing logics CSV rows."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Iterable, Sequence

import pandas as pd


CSV_FIELDNAMES = [
    "Target",
    "Source",
    "Constraint",
    "B/F Relationship",
    "Comment",
    "Is Implemented",
    "Custom Query",
    "ID",
]


def normalize_quotes(value):
    """Normalize smart quotes and strip surrounding quotes from strings."""
    replacements = {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "‚": "'",
        "‛": "'",
        "„": '"',
        "‟": '"',
        "❝": '"',
        "❞": '"',
        "❮": "<",
        "❯": ">",
    }
    if isinstance(value, str):
        for original, replacement in replacements.items():
            value = value.replace(original, replacement)
        return value.strip().strip('"').strip("'")
    if isinstance(value, list):
        return [normalize_quotes(item) for item in value]
    return value


def parse_reference_cell(value) -> str | list[str]:
    """Parse Source/Target CSV cells into either a string or list of strings."""
    value = normalize_quotes(value)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return str(value).strip()

    stripped = value.strip()
    if not stripped:
        return ""
    if not stripped.startswith("["):
        return stripped

    try:
        parsed = ast.literal_eval(stripped)
    except (SyntaxError, ValueError):
        parsed = [
            part.strip().strip("'").strip('"').strip("’")
            for part in stripped.strip("[]").split(",")
        ]

    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return str(parsed).strip()


def reference_values(value) -> list[str]:
    """Return all variable references from a Source/Target cell."""
    parsed = parse_reference_cell(value)
    if isinstance(parsed, list):
        return parsed
    return [parsed] if parsed else []


def is_blank(value) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == ""


def parse_is_implemented(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return True
    normalized = str(value).strip().lower()
    return normalized not in {"no", "false", "0", "n"}


def require_logics_columns(df: pd.DataFrame) -> None:
    missing = [col for col in CSV_FIELDNAMES if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required logics CSV columns: {missing}")


@dataclass(frozen=True)
class LogicsCsvRow:
    target: str | list[str]
    source: str | list[str]
    constraint: str
    relationship: str
    comment: str
    is_implemented: bool
    custom_query: str
    row_id: str

    @property
    def target_vars(self) -> list[str]:
        return self.target if isinstance(self.target, list) else ([self.target] if self.target else [])

    @property
    def source_vars(self) -> list[str]:
        return self.source if isinstance(self.source, list) else ([self.source] if self.source else [])


def parse_logics_dataframe(df: pd.DataFrame) -> list[LogicsCsvRow]:
    require_logics_columns(df)
    rows: list[LogicsCsvRow] = []
    for _, row in df.iterrows():
        rows.append(
            LogicsCsvRow(
                target=parse_reference_cell(row["Target"]),
                source=parse_reference_cell(row["Source"]),
                constraint="" if is_blank(row["Constraint"]) else str(row["Constraint"]).strip(),
                relationship=""
                if is_blank(row["B/F Relationship"])
                else str(row["B/F Relationship"]).strip(),
                comment="" if is_blank(row["Comment"]) else str(row["Comment"]).strip(),
                is_implemented=parse_is_implemented(row["Is Implemented"]),
                custom_query="" if is_blank(row["Custom Query"]) else str(row["Custom Query"]).strip(),
                row_id="" if is_blank(row["ID"]) else str(row["ID"]).strip(),
            )
        )
    return rows


def find_missing_references(
    df: pd.DataFrame,
    data_columns: Iterable[str],
    reference_columns: Sequence[str] = ("Source", "Target"),
) -> list[str]:
    """Find referenced columns missing from a dataset, ignoring blank cells."""
    data_set = {normalize_quotes(str(col)).strip().lower() for col in data_columns}
    references: set[str] = set()
    for col in reference_columns:
        if col not in df.columns:
            continue
        for value in df[col]:
            for ref in reference_values(value):
                references.add(normalize_quotes(str(ref)).strip().lower())
    return sorted(ref for ref in references if ref and ref not in data_set)
