"""Backfill FairsetReview-style ``.xlsx`` from ``fairset_report.json`` when missing on disk."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.main import app
from tests.test_fairset_report_xlsx_layout import assert_fairset_review_xlsx_layout


def test_get_run_materializes_xlsx_when_only_report_json_exists(tmp_path: Path) -> None:
    app.state.runs_root = tmp_path
    run_id = "run_materialize_xlsx_01"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "fairset_report.json").write_text(
        json.dumps(
            [
                {
                    "Type": "Block Single-to-Single",
                    "Description": "x",
                    "Detail": "d",
                    "is_valid": False,
                    "is_supported": True,
                    "Percentage_of_valid_rows": 50.0,
                    "Rows": [0],
                    "Dataframe": [{"Q1": "1"}],
                }
            ]
        ),
        encoding="utf-8",
    )
    inputs_dir = run_dir / "inputs"
    inputs_dir.mkdir()
    (inputs_dir / "fairset.csv").write_text("c1,c2\nv1,v2\n", encoding="utf-8")

    client = TestClient(app)
    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    assert (run_dir / "fairset_report.xlsx").is_file()
    body = response.json()
    assert body["artifacts"]["fairset_report_xlsx"] == "fairset_report.xlsx"
    assert_fairset_review_xlsx_layout((run_dir / "fairset_report.xlsx").read_bytes())
