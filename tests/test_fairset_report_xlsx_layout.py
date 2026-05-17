"""Fairset ``.xlsx`` must embed the FairsetReview-style layout (not a CSV disguise)."""

from __future__ import annotations

import io
import zipfile

from logic_platform.fairset.report_xlsx import fairset_report_to_xlsx_bytes


def assert_fairset_review_xlsx_layout(blob: bytes) -> None:
    """Raises AssertionError when the workbook is missing banner merges / branded strings."""
    assert blob[:2] == b"PK", "expected ZIP package for .xlsx"
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        sheets = sorted(
            n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")
        )
        assert sheets, "expected at least one worksheet"
        sheet_xml = zf.read(sheets[0]).decode("utf-8", errors="replace")
        assert "<mergeCells" in sheet_xml, "missing merged banner — layout exporter not applied"
        assert "xl/sharedStrings.xml" in zf.namelist()
        shared = zf.read("xl/sharedStrings.xml").decode("utf-8", errors="replace")
        assert "Logic Attainement" in shared
        assert "REPORT" in shared
        assert "List of limitations" in shared


def test_fairset_report_to_xlsx_bytes_has_workbook_layout():
    report = [
        {
            "Type": "Block Single-to-Single",
            "Description": "Block (Q1 to Q2)",
            "Detail": "comment",
            "is_valid": False,
            "is_supported": True,
            "Percentage_of_valid_rows": 50.0,
            "Occurrences_train": 2,
            "Rows": [0],
            "Dataframe": [{"Q1": "1", "Q2": "shown"}],
        }
    ]
    blob = fairset_report_to_xlsx_bytes(report, fairset_row_count=10)
    assert_fairset_review_xlsx_layout(blob)
