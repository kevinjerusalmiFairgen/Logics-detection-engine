"""FairsetReview-style Excel report — mirrors ``scripts/generate_report.export_to_excel``."""

from __future__ import annotations

import io
import math
from typing import Any

import pandas as pd
import xlsxwriter

from logic_platform.fairset.report_table import (
    FAIRSET_REVIEW_DISPLAY_COLUMNS,
    affected_row_index_count,
    fairset_review_report_dataframe,
)

# Column widths tuned to match FairsetReview readability (was uniform 30 in the script).
_COLUMN_WIDTHS: dict[str, float] = {
    "Logic Type": 24,
    "Description": 48,
    "Columns": 30,
    "Percentage of rows impacted": 22,
    "Number of impacted rows": 22,
    "Wrong rows's index": 14,
    "Supported": 14,
}


def fairset_report_to_xlsx_bytes(
    report: list[dict[str, Any]],
    *,
    fairset_row_count: int | None = None,
) -> bytes:
    """Write the Fairset summary workbook (same structure and styling as FairsetReview).

    Enhancements versus the original narrow ``B:E`` banner merge: the green header band
    spans all data columns so the sheet stays aligned when the table is wider than four columns.
    """
    df = fairset_review_report_dataframe(report)
    buf = io.BytesIO()
    workbook = xlsxwriter.Workbook(buf, {"in_memory": True, "nan_inf_to_errors": True})
    worksheet = workbook.add_worksheet("Table")

    banner_format = workbook.add_format(
        {
            "bold": True,
            "font_name": "Roboto",
            "font_size": 14,
            "bg_color": "#143126",
            "font_color": "white",
        }
    )

    column_header_format = workbook.add_format(
        {
            "bold": True,
            "font_name": "Roboto",
            "font_size": 11,
            "bg_color": "#ccffcb",
            "border": 1,
            "align": "center",
            "valign": "vcenter",
        }
    )

    data_format = workbook.add_format(
        {
            "font_name": "Roboto",
            "font_size": 10,
            "align": "left",
            "valign": "vcenter",
            "border": 1,
            "text_wrap": True,
            "bold": False,
        }
    )

    title_format = workbook.add_format(
        {
            "bold": True,
            "font_size": 12,
            "font_name": "Roboto",
            "align": "left",
        }
    )

    summary_format = workbook.add_format(
        {
            "bold": True,
            "font_size": 11,
            "font_name": "Roboto",
            "align": "right",
        }
    )

    empty_state_format = workbook.add_format(
        {
            "font_name": "Roboto",
            "font_size": 11,
            "italic": True,
            "align": "center",
            "valign": "vcenter",
            "bg_color": "#f4f9f6",
            "border": 1,
            "text_wrap": True,
        }
    )

    worksheet.set_row(0, 20, banner_format)
    worksheet.set_row(1, 20, banner_format)
    worksheet.set_row(2, 20, banner_format)

    columns = list(df.columns) if len(df.columns) else list(FAIRSET_REVIEW_DISPLAY_COLUMNS)
    num_cols = max(len(columns), 1)

    start_row = 7
    start_col = 1

    end_col_idx = start_col + num_cols - 1

    # Full-width banner (FairsetReview used B1:E2 / B3:E3; we extend to the full table width).
    worksheet.merge_range(0, start_col, 1, end_col_idx, "Logic Attainement", banner_format)
    worksheet.merge_range(2, start_col, 2, end_col_idx, "REPORT", banner_format)

    worksheet.write(start_row - 2, start_col, "List of limitations:", title_format)

    for col_num, col_name in enumerate(columns):
        worksheet.write(start_row, start_col + col_num, col_name, column_header_format)

    last_data_row = start_row
    if df.empty:
        worksheet.merge_range(
            start_row + 1,
            start_col,
            start_row + 1,
            end_col_idx,
            "No logic limitations detected — all checks passed.",
            empty_state_format,
        )
        worksheet.set_row(start_row + 1, 40)
        last_data_row = start_row + 1
    else:
        for row_num, (_, row) in enumerate(df.iterrows()):
            max_lines = 1
            for col_num, (col_name, cell_value) in enumerate(row.items()):
                cell_str = str(cell_value) if pd.notna(cell_value) else ""
                worksheet.write(start_row + row_num + 1, start_col + col_num, cell_str, data_format)

                if col_name != "Wrong rows's index":
                    est_lines = math.ceil(len(cell_str) / 30) if cell_str else 1
                    max_lines = max(max_lines, est_lines)

            row_height = max(20, max_lines * 15)
            worksheet.set_row(start_row + row_num + 1, row_height)

        last_data_row = start_row + len(df)
        worksheet.autofilter(start_row, start_col, last_data_row, end_col_idx)
        # Top-left scrollable cell: first data row (header stays visible).
        worksheet.freeze_panes(start_row + 1, start_col)

    for i, name in enumerate(columns):
        width = _COLUMN_WIDTHS.get(name, 28)
        opts: dict[str, Any] = {"hidden": True} if name == "Wrong rows's index" else {}
        worksheet.set_column(start_col + i, start_col + i, width, None, opts)

    total_index_count = affected_row_index_count(df)
    summary_row = last_data_row + 2
    summary_row_pct = last_data_row + 3

    visible_cols = [col for col in columns if col != "Wrong rows's index"]
    last_visible_col_index = len(visible_cols) - 1 if visible_cols else 0
    summary_col = start_col - 1 + max(last_visible_col_index, 0)

    worksheet.write(
        summary_row,
        summary_col,
        f"Number of rows affected: {total_index_count}",
        summary_format,
    )
    if fairset_row_count and fairset_row_count > 0:
        pct = round(total_index_count * 100 / fairset_row_count, 2)
        worksheet.write(
            summary_row_pct,
            summary_col,
            f"Percentage of rows affected: {pct}",
            summary_format,
        )

    workbook.close()
    return buf.getvalue()
