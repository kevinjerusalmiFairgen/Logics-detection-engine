"""Normalize Fairgen structure.json output."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from logic_platform.logics_csv import reference_values
from logic_platform.utils import flatten_vars


HELPER_COLUMN_PATTERNS = (
    re.compile(r"_Rank\d+$", re.IGNORECASE),
    re.compile(r"r98oe$", re.IGNORECASE),
)


def normalize_structure(
    structure: dict[str, Any] | None,
    *,
    prior_df: pd.DataFrame | None = None,
    questionnaire: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return NBA/Fairgen-style structure JSON.

    Streamlit's legacy parser is still the source for constraints, recodings,
    and typeOfNan. This function only shapes the structure contract expected by
    Fairgen: multiSelect entries use `columns`, include metadata, and never use
    `codes`.

    Recoding entries (backward compatible with historic Fairgen JSON):

    - ``codes``: always a JSON array of source variable strings (never a bare
      string), including a single source.
    - ``recode``: a **string** when there is exactly one target variable, or **empty
      string** when none (legacy tooling); a JSON **array** of strings when there
      are multiple targets.
    """
    if not isinstance(structure, dict):
        structure = {}
    normalized = {
        "recodings": _dedupe_recodings(
            _normalize_recoding_arrays(structure.get("recodings", []))
        ),
        "multiSelect": _build_multiselects(structure, prior_df, questionnaire),
        "typeOfNan": structure.get("typeOfNan", []),
    }
    return normalized


def _recoding_vars_as_list(value: Any) -> list[str]:
    """Normalize a list of dataset variable names: always a JSON array of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    s = str(value).strip()
    if not s:
        return []
    return [s]


def _looks_like_structure_recoding_dict(value: dict[str, Any]) -> bool:
    """Heuristic for Fairgen recoding-rule objects vs arbitrary dicts."""
    return "codes" in value or "recode" in value


def _finalize_recoding_entry(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one recoding object for serialization.

    - ``codes``: always ``list[str]`` (supports legacy scalar strings or arrays on input).
    - ``recode``: Fairgen-compatible encoding — singular target as ``str``, multiple as ``list[str]``.
    """
    out = dict(item)
    codes = _recoding_vars_as_list(out.get("codes"))
    targets = _recoding_vars_as_list(out.get("recode"))
    out["codes"] = codes
    if len(targets) <= 1:
        out["recode"] = targets[0] if targets else ""
    else:
        out["recode"] = targets
    return out


def _normalize_recoding_arrays(values: list[Any]) -> list[Any]:
    """Normalize recodings for structure.json (read-tolerant; write compat)."""
    out: list[Any] = []
    for value in values:
        if isinstance(value, dict):
            out.append(_finalize_recoding_entry(value))
        else:
            out.append(value)
    return out


def coerce_recodings_deep(obj: Any) -> Any:
    """Walk JSON-shaped dict/list trees and normalize every ``recodings`` list.

    Fairgen-era exports sometimes place structure-like rows under nested keys or
    inside ``fairset_constraints.json``. Constraint rows stored as bare lists/tuples
    are left unchanged; only dict entries that look like recoding metadata are
    coerced (scalar ``codes`` → ``list[str]``, etc.).

    Does not apply ``_dedupe_recodings`` (constraint lists may legitimately repeat).
    """
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            if key == "recodings" and isinstance(value, list):
                out[key] = [
                    _finalize_recoding_entry(item)
                    if isinstance(item, dict) and _looks_like_structure_recoding_dict(item)
                    else coerce_recodings_deep(item)
                    for item in value
                ]
            else:
                out[key] = coerce_recodings_deep(value)
        return out
    if isinstance(obj, list):
        return [coerce_recodings_deep(x) for x in obj]
    return obj


def coerce_structure_recodings(structure: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with all nested ``recodings`` lists normalized; top-level deduped.

    Useful when loading mixed-era ``structure.json`` files without rebuilding multiSelect.
    """
    deep = coerce_recodings_deep(structure)
    if not isinstance(deep, dict):
        return dict(structure)
    out = dict(deep)
    if isinstance(out.get("recodings"), list):
        out["recodings"] = _dedupe_recodings(out["recodings"])
    return out


def _build_multiselects(
    structure: dict[str, Any],
    prior_df: pd.DataFrame | None,
    questionnaire: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}

    for item in _questionnaire_multiselects(questionnaire):
        by_id[item["id"]] = item

    for item in _prior_multiselects(prior_df):
        if not _has_columns(by_id.values(), item["columns"]):
            by_id.setdefault(item["id"], item)

    for item in structure.get("multiSelect", []):
        if not isinstance(item, dict):
            continue
        columns = _clean_columns(item.get("columns") or item.get("codes") or [])
        if not columns or _has_columns(by_id.values(), columns):
            continue
        item_id = _infer_group_id(str(item.get("id") or item.get("name") or columns[0]))
        by_id.setdefault(
            item_id,
            _multiselect_item(
                item_id=item_id,
                name=str(item.get("name") or item_id),
                columns=columns,
                labels={},
            ),
        )

    return list(by_id.values())


def _has_columns(items, columns: list[str]) -> bool:
    target = tuple(columns)
    return any(tuple(item.get("columns", [])) == target for item in items)


def _questionnaire_multiselects(questionnaire: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not questionnaire:
        return []

    raw_questions = questionnaire.get("questions")
    if raw_questions is None:
        raw_questions = []
    if not isinstance(raw_questions, list):
        return []

    out: list[dict[str, Any]] = []
    for question in raw_questions:
        if not isinstance(question, dict):
            continue
        if question.get("type") != "multi_select":
            continue
        columns = _clean_columns([str(value) for value in flatten_vars(question.get("vars", []))])
        if not columns:
            continue
        question_id = str(question.get("id") or _infer_group_id(columns[0]))
        out.append(
            _multiselect_item(
                item_id=question_id,
                name=str(question.get("text") or question_id),
                columns=columns,
                labels=_answer_labels(question),
            )
        )
    return out


def _prior_multiselects(prior_df: pd.DataFrame | None) -> list[dict[str, Any]]:
    if prior_df is None or "Constraint" not in prior_df.columns or "Target" not in prior_df.columns:
        return []

    out: list[dict[str, Any]] = []
    for _, row in prior_df.iterrows():
        if str(row.get("Constraint", "")).strip() != "MultiSelect":
            continue
        columns = _clean_columns(reference_values(row.get("Target")))
        if not columns:
            continue
        item_id = _infer_group_id(columns[0])
        name = _name_from_comment(row.get("Comment"), item_id)
        out.append(_multiselect_item(item_id=item_id, name=name, columns=columns, labels={}))
    return out


def _multiselect_item(
    *,
    item_id: str,
    name: str,
    columns: list[str],
    labels: dict[str, str],
) -> dict[str, Any]:
    return {
        "id": item_id,
        "name": name,
        "columns": columns,
        "dataType": "LITERAL",
        "contentType": "BINARY_MULTISELECT",
        "shortColumnLabel": [
            {"name": column, "label": labels.get(column, column)} for column in columns
        ],
    }


def _clean_columns(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        column = str(value).strip()
        if not column or _is_helper_column(column) or column in seen:
            continue
        seen.add(column)
        out.append(column)
    return out


def _is_helper_column(column: str) -> bool:
    return any(pattern.search(column) for pattern in HELPER_COLUMN_PATTERNS)


def _infer_group_id(column: str) -> str:
    match = re.match(r"^(.+?)(?:r\d+.*|_[Rr]ank\d+)?$", column)
    return match.group(1) if match else column


def _name_from_comment(value: Any, fallback: str) -> str:
    comment = "" if value is None else str(value).strip()
    if not comment:
        return fallback
    if ":" in comment:
        _, name = comment.split(":", 1)
        return name.strip() or fallback
    return comment


def _answer_labels(question: dict[str, Any]) -> dict[str, str]:
    answers = question.get("answers") or {}
    labels: dict[str, str] = {}

    if isinstance(answers, dict):
        for key, value in answers.items():
            if isinstance(value, dict):
                column = str(value.get("var") or value.get("name") or key)
                label = str(value.get("label") or value.get("text") or value.get("answer") or key)
            else:
                column = str(key)
                label = str(value)
            labels[column] = label

    if isinstance(answers, list):
        for answer in answers:
            if not isinstance(answer, dict):
                continue
            column = str(answer.get("var") or answer.get("name") or answer.get("column") or "")
            if not column:
                continue
            labels[column] = str(
                answer.get("label") or answer.get("text") or answer.get("answer") or column
            )

    return labels


def _dedupe_recodings(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for value in values:
        key = repr(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out
