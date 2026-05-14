"""Headless parser for Fairset prior/logics CSV files."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from logic_platform.logics_csv import (
    LogicsCsvRow,
    find_missing_references,
    parse_logics_dataframe,
)


CONSTRAINT_KEYS = [
    "BF_SS",
    "BF_SM",
    "BF_MS",
    "BF_MM",
    "uniqueness",
    "count",
    "recodings",
    "NOTAs",
    "AOTAs",
    "parallel piping",
    "custom",
]


@dataclass(frozen=True)
class ParseWarning:
    row_id: str
    message: str


@dataclass
class PriorParseResult:
    constraints: dict[str, list] = field(
        default_factory=lambda: {key: [] for key in CONSTRAINT_KEYS}
    )
    structure: dict[str, list] = field(
        default_factory=lambda: {"recodings": [], "multiSelect": [], "typeOfNan": []}
    )
    warnings: list[ParseWarning] = field(default_factory=list)


def parse_prior_dataframe(df: pd.DataFrame) -> PriorParseResult:
    """Convert a logics/prior CSV dataframe into Fairset constraints and structure."""
    rows = parse_logics_dataframe(df)
    result = PriorParseResult()
    for index, row in enumerate(rows):
        _append_row(result, index, row)
    return result


def validate_referenced_columns(
    prior_df: pd.DataFrame, data_columns, reference_columns=("Source", "Target")
) -> list[str]:
    """Return missing referenced columns while ignoring blank Source/Target cells."""
    return find_missing_references(prior_df, data_columns, reference_columns)


def _append_row(result: PriorParseResult, index: int, row: LogicsCsvRow) -> None:
    if row.custom_query:
        result.constraints["custom"].append(
            [row.constraint, row.comment, row.custom_query, row.is_implemented]
        )
        return

    if row.constraint in {"Block", "Force", "Block/Force", "Dynamic Piping"}:
        _append_block_force(result, row)
    elif row.constraint == "Parallel Piping":
        result.constraints["BF_MM"].append(
            [
                row.source,
                row.target,
                [],
                row.comment,
                "block_force",
                row.is_implemented,
            ]
        )
    elif row.constraint == "Uniqueness":
        result.constraints["uniqueness"].append([row.target, row.is_implemented])
    elif row.constraint == "Count":
        result.constraints["count"].append([row.target, row.source, row.is_implemented])
    elif row.constraint == "Recoding":
        _append_recoding(result, index, row)
    elif row.constraint == "None of the above":
        result.constraints["NOTAs"].append([row.source, row.target, [], row.is_implemented])
    elif row.constraint == "All of the above":
        result.constraints["AOTAs"].append([row.source, row.target, [], row.is_implemented])
    elif row.constraint == "MultiSelect":
        result.structure["multiSelect"].append(
            {"id": str(index), "name": str(index), "columns": row.target}
        )
    elif row.constraint:
        result.warnings.append(
            ParseWarning(row_id=row.row_id, message=f"Unsupported constraint: {row.constraint}")
        )


def _append_block_force(result: PriorParseResult, row: LogicsCsvRow) -> None:
    mode = row.constraint.lower().replace("/", "_").replace(" ", "_")
    if not row.relationship:
        result.warnings.append(
            ParseWarning(row_id=row.row_id, message="Missing relationship for Block/Force")
        )
        return
    if row.relationship == "Single to Single":
        result.constraints["BF_SS"].append(
            [row.source, row.target, row.comment, mode, row.is_implemented]
        )
    elif row.relationship == "Single to Multi":
        result.constraints["BF_SM"].append(
            [
                row.source,
                row.target,
                row.comment,
                row.constraint.lower().replace("/", "_"),
                row.is_implemented,
            ]
        )
    elif row.relationship == "Multi to Single":
        result.constraints["BF_MS"].append(
            [row.target, row.source, row.comment, row.is_implemented]
        )
    else:
        result.warnings.append(
            ParseWarning(
                row_id=row.row_id,
                message=f"Unsupported Block/Force relationship: {row.relationship}",
            )
        )


def _append_recoding(result: PriorParseResult, index: int, row: LogicsCsvRow) -> None:
    if not row.relationship:
        result.warnings.append(
            ParseWarning(row_id=row.row_id, message="Missing relationship for Recoding")
        )
        return

    mode_by_relationship = {
        "Single to Single": "SS",
        "Single to Multi": "SM",
        "Multi to Single": "MS",
        "Multi to Multi": "MM",
    }
    mode = mode_by_relationship.get(row.relationship)
    if mode is None:
        result.warnings.append(
            ParseWarning(
                row_id=row.row_id,
                message=f"Unsupported Recoding relationship: {row.relationship}",
            )
        )
        return

    if mode in {"SS", "MS"}:
        targets = list(row.target_vars)
        sources = list(row.source_vars)
        if len(targets) <= 1:
            recode_field: str | list[str] = targets[0] if targets else ""
        else:
            recode_field = targets
        result.structure["recodings"].append(
            {
                "id": str(index),
                "name": str(index),
                "recode": recode_field,
                "codes": sources,
            }
        )

    result.constraints["recodings"].append(
        [row.source, row.target, mode, row.comment, row.is_implemented]
    )
