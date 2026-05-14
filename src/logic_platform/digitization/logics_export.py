"""Export final questionnaire JSON as the platform logics JSON artifact."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from logic_platform.logics.extract_logic_table import (
    CSV_FIELDNAMES,
    _internal_to_export_rows,
    extract_all_logics,
    extract_multiselect_group_rows,
)
from logic_platform.digitization.steps.s7_assemble import materialize_recode_logics


@dataclass(frozen=True)
class LogicsJsonExport:
    rows: list[dict[str, str]]
    payload: dict[str, Any]


def export_logics_json_from_questionnaire(
    questionnaire_json: dict[str, Any],
    pattern_report: dict[str, Any] | None = None,
    include_multiselect_groups: bool = True,
) -> LogicsJsonExport:
    """Create the logics JSON payload from final questionnaire JSON."""
    working = copy.deepcopy(questionnaire_json)
    materialize_recode_logics(
        working.get("questions", []),
        working.get("derived_variables", []),
    )

    internal_rows = extract_all_logics(working)
    if include_multiselect_groups:
        internal_rows.extend(extract_multiselect_group_rows(working, pattern_report))

    rows = _internal_to_export_rows(internal_rows)
    payload = {
        "schema": "logic_platform.logics.v1",
        "row_count": len(rows),
        "columns": CSV_FIELDNAMES,
        "rows": rows,
    }
    return LogicsJsonExport(rows=rows, payload=payload)
