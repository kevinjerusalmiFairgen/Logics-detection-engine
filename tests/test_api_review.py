from io import BytesIO

from fastapi.testclient import TestClient

from apps.api.main import app
from tests.test_fairset_report_xlsx_layout import assert_fairset_review_xlsx_layout


def test_review_endpoint_runs_headless_bf_ss_review_and_writes_report(tmp_path):
    app.state.runs_root = tmp_path
    client = TestClient(app)
    logics_csv = (
        "Target,Source,Constraint,B/F Relationship,Comment,Is Implemented,Custom Query,ID\n"
        "Q2,Q1,Block,Single to Single,Block Q2 when Q1 is 1,Yes,,1\n"
    ).encode("utf-8")
    train_csv = "Q1,Q2\n1,\n1,\n2,shown\n".encode("utf-8")
    fairset_csv = "Q1,Q2\n1,should be blank\n2,shown\n".encode("utf-8")

    response = client.post(
        "/runs/review",
        files={
            "train_file": ("train.csv", BytesIO(train_csv), "text/csv"),
            "fairset_file": ("fairset.csv", BytesIO(fairset_csv), "text/csv"),
            "logics_file": ("logics.csv", BytesIO(logics_csv), "text/csv"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["missing_columns"] == []
    assert body["warnings"] == []
    assert body["report"][0]["is_valid"] is False
    assert body["report"][0]["Rows"] == [0]
    run_dir = tmp_path / body["run_id"]
    assert (run_dir / "fairset_report.csv").is_file()
    assert (run_dir / "fairset_report.json").is_file()
    assert (run_dir / "fairset_report.xlsx").is_file()
    assert body["artifacts"]["fairset_report"] == "fairset_report.csv"
    assert body["artifacts"]["fairset_report_json"] == "fairset_report.json"
    assert body["artifacts"]["fairset_report_xlsx"] == "fairset_report.xlsx"

    xlsx_dl = client.get(f"/runs/{body['run_id']}/artifacts/fairset_report_xlsx")
    assert xlsx_dl.status_code == 200
    cd = xlsx_dl.headers.get("content-disposition") or ""
    assert "FairsetReview.xlsx" in cd
    ct = (xlsx_dl.headers.get("content-type") or "").lower()
    assert "spreadsheetml.sheet" in ct or "officedocument.spreadsheetml" in ct
    assert xlsx_dl.content[:2] == b"PK"
    assert_fairset_review_xlsx_layout(xlsx_dl.content)
    assert_fairset_review_xlsx_layout((run_dir / "fairset_report.xlsx").read_bytes())


def test_review_endpoint_reports_missing_columns_without_evaluation(tmp_path):
    app.state.runs_root = tmp_path
    client = TestClient(app)
    logics_csv = (
        "Target,Source,Constraint,B/F Relationship,Comment,Is Implemented,Custom Query,ID\n"
        "MISSING,Q1,Block,Single to Single,Bad target,Yes,,1\n"
    ).encode("utf-8")
    train_csv = "Q1\n1\n".encode("utf-8")
    fairset_csv = "Q1\n1\n".encode("utf-8")

    response = client.post(
        "/runs/review",
        files={
            "train_file": ("train.csv", BytesIO(train_csv), "text/csv"),
            "fairset_file": ("fairset.csv", BytesIO(fairset_csv), "text/csv"),
            "logics_file": ("logics.csv", BytesIO(logics_csv), "text/csv"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["missing_columns"] == ["missing"]
    assert body["report"] == []
