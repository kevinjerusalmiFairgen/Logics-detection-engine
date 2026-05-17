import csv
from io import StringIO

import pytest

from logic_platform.fairset.report_csv import fairset_report_to_csv
from logic_platform.fairset.report_table import FAIRSET_REVIEW_DISPLAY_COLUMNS, convert_logic_type
from logic_platform.fairset.report_xlsx import fairset_report_to_xlsx_bytes


def test_fairset_csv_uses_fairsetreview_columns_and_failure_rows_only():
    report = [
        {
            "Type": "Block Single-to-Single",
            "Description": "Block (Q1 to Q2)",
            "Detail": "comment",
            "is_valid": False,
            "is_supported": True,
            "Percentage_of_valid_rows": 50.0,
            "Occurrences_train": 2,
            "Rows": [0, 3],
            "Dataframe": [{"Q1": "1", "Q2": "should be blank"}],
        },
        {
            "Type": "BF_MM",
            "Description": "stub",
            "Detail": "",
            "is_valid": True,
            "is_supported": False,
            "Percentage_of_valid_rows": 100.0,
            "Occurrences_train": 0,
            "Rows": [],
        },
    ]
    csv_text = fairset_report_to_csv(report)
    rows = list(csv.DictReader(StringIO(csv_text)))
    assert len(rows) == 1
    assert rows[0]["Logic Type"] == "Skip Logic"
    assert rows[0]["Supported"] == "Yes"
    assert rows[0]["Columns"] == "Q1, Q2"
    assert float(rows[0]["Percentage of rows impacted"]) == 50.0
    assert rows[0]["Number of impacted rows"] == "2"
    assert "0" in rows[0]["Wrong rows's index"] and "3" in rows[0]["Wrong rows's index"]
    first_line = csv_text.splitlines()[0]
    header_row = next(csv.reader([first_line]))
    assert header_row == list(FAIRSET_REVIEW_DISPLAY_COLUMNS)


def test_fairset_csv_headers_only_when_no_failures():
    report = [
        {
            "Type": "BF_MM",
            "is_valid": True,
            "is_supported": True,
            "Percentage_of_valid_rows": 100.0,
            "Rows": [],
            "Dataframe": None,
            "Detail": "",
            "Description": "ok",
        }
    ]
    csv_text = fairset_report_to_csv(report)
    lines = csv_text.strip().splitlines()
    assert len(lines) == 1
    header_row = next(csv.reader([lines[0]]))
    assert header_row == list(FAIRSET_REVIEW_DISPLAY_COLUMNS)


def test_fairset_xlsx_roundtrip_smoke():
    report = [
        {
            "Type": "Uniqueness",
            "Description": "Unique ranking",
            "Detail": "",
            "is_valid": False,
            "is_supported": True,
            "Percentage_of_valid_rows": 90.0,
            "Occurrences_train": 1,
            "Rows": [0],
            "Dataframe": [{"a": 1}],
        }
    ]
    blob = fairset_report_to_xlsx_bytes(report, fairset_row_count=10)
    assert blob.startswith(b"PK")
    assert len(blob) > 2000


@pytest.mark.parametrize(
    ("raw_type", "expected"),
    [
        ("Block Single-to-Single", "Skip Logic"),
        ("Force Single-to-Single", "Mandatory Logic"),
        ("Uniqueness", "Ranking"),
        ("Count", "Selection Limit Control"),
    ],
)
def test_convert_logic_type_parity(raw_type, expected):
    assert convert_logic_type(raw_type) == expected
