"""Headless Fairset validation services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from logic_platform.fairset.analysis import (
    check_columns_presence,
    prior_file_extract,
    run_logic_analysis,
)
from logic_platform.fairset.structure import normalize_structure


@dataclass(frozen=True)
class ReviewResult:
    constraints: dict[str, list]
    structure: dict[str, list]
    report: list[dict[str, Any]]
    warnings: list[dict[str, str]]
    missing_columns: list[str]


def run_review_from_dataframes(
    prior_df: pd.DataFrame,
    train_df: pd.DataFrame,
    fairset_df: pd.DataFrame,
    questionnaire: dict[str, Any] | None = None,
) -> ReviewResult:
    missing_columns = check_columns_presence(prior_df, train_df, ["Source", "Target"])
    constraints, raw_structure = prior_file_extract(prior_df)
    structure = normalize_structure(
        raw_structure,
        prior_df=prior_df,
        questionnaire=questionnaire,
    )
    warnings: list[dict[str, str]] = []

    if missing_columns and missing_columns != [""]:
        return ReviewResult(
            constraints=constraints,
            structure=structure,
            report=[],
            warnings=warnings,
            missing_columns=missing_columns,
        )

    report = run_logic_analysis(constraints, train_df, fairset_df, empty_values=[])
    return ReviewResult(
        constraints=constraints,
        structure=structure,
        report=report,
        warnings=warnings,
        missing_columns=[],
    )


def evaluate_constraints(
    constraints: dict[str, list] | None, train_df: pd.DataFrame, fairset_df: pd.DataFrame
) -> list[dict[str, Any]]:
    report: list[dict[str, Any]] = []
    if not isinstance(constraints, dict):
        constraints = {}
    for constraint in constraints.get("BF_SS", []) or []:
        source, target, detail, mode, is_supported = constraint
        if mode == "block_force":
            report.append(
                evaluate_bf_ss(train_df, fairset_df, source, target, detail, "block", is_supported)
            )
            report.append(
                evaluate_bf_ss(train_df, fairset_df, source, target, detail, "force", is_supported)
            )
        else:
            report.append(
                evaluate_bf_ss(train_df, fairset_df, source, target, detail, mode, is_supported)
            )

    unsupported_counts = {
        key: len(value)
        for key, value in constraints.items()
        if key != "BF_SS" and isinstance(value, list) and value
    }
    for key, count in unsupported_counts.items():
        report.append(
            {
                "Type": key,
                "Description": f"{key} validation is not implemented in the new service yet",
                "is_valid": True,
                "is_supported": False,
                "Dataframe": None,
                "Detail": f"{count} constraint(s) parsed but not evaluated yet",
                "Occurrences_train": 0,
                "Percentage_of_valid_rows": 100.0,
                "Rows": [],
            }
        )
    return report


def evaluate_bf_ss(
    train_df: pd.DataFrame,
    fairset_df: pd.DataFrame,
    source: str,
    target: str,
    detail: str,
    mode: str,
    is_supported: bool = True,
) -> dict[str, Any]:
    train = train_df[[source, target]].copy()
    fairset = fairset_df[[source, target]].copy()

    train[source] = train[source].apply(lambda value: str(value) if pd.notna(value) else value)
    train[target] = train[target].apply(lambda value: str(value) if pd.notna(value) else value)
    fairset[source] = fairset[source].apply(lambda value: str(value) if pd.notna(value) else value)
    fairset[target] = fairset[target].apply(lambda value: str(value) if pd.notna(value) else value)

    nan_triggers = train.groupby(source, dropna=False)[target].apply(lambda col: col.isna().all())
    anti_nan_triggers = train.groupby(source, dropna=False)[target].apply(
        lambda col: ~col.isna().any()
    )
    block_triggers = nan_triggers[nan_triggers].index.values
    force_triggers = nan_triggers[anti_nan_triggers].index.values

    if mode == "force":
        violations = fairset[fairset[source].isin(force_triggers) & fairset[target].isna()][
            [source, target]
        ]
        type_label = "Force Single-to-Single"
    else:
        violations = fairset[fairset[source].isin(block_triggers) & fairset[target].notna()][
            [source, target]
        ]
        type_label = "Block Single-to-Single"

    rows = violations.index.tolist()
    valid_rows = round(100 - (len(rows) * 100 / fairset_df.shape[0]), 2) if len(fairset_df) else 100
    return {
        "Type": type_label,
        "Description": f"{type_label} ({source} to {target})",
        "is_valid": violations.empty,
        "is_supported": is_supported,
        "Dataframe": violations.to_dict(orient="records") if not violations.empty else None,
        "Detail": detail,
        "Occurrences_train": 0 if violations.empty else len(train[train[source].isin(violations[source].unique())]),
        "Percentage_of_valid_rows": valid_rows,
        "Rows": rows,
    }
