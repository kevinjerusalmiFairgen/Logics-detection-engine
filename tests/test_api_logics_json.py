from io import BytesIO

from fastapi.testclient import TestClient

import apps.api.main as api_main
from apps.api.main import app


def fake_pipeline(pdf_path, data_path, artifacts, *, engine="manus", skip_validation=True):
    questionnaire = {
        "derived_variables": [],
        "questions": [
            {
                "id": "Q1",
                "section": "S",
                "text": "Choose",
                "type": "multi_select",
                "vars": ["Q1r1", "Q1r2"],
                "answers": {"Q1r1": "Yes", "Q1r2": "No"},
                "logics": [],
            }
        ],
    }
    artifacts.write_json("questionnaire_final", questionnaire)
    return questionnaire


def test_logics_from_questionnaire_endpoint_outputs_only_logics_json(tmp_path):
    app.state.runs_root = tmp_path
    client = TestClient(app)
    questionnaire = b"""{
      "derived_variables": [],
      "questions": [
        {
          "id": "Q1",
          "section": "S",
          "text": "Choose",
          "type": "multi_select",
          "vars": ["Q1r1", "Q1r2"],
          "answers": {},
          "logics": []
        }
      ]
    }"""

    response = client.post(
        "/runs/logics/from-questionnaire",
        files={
            "questionnaire_file": (
                "questionnaire_final.json",
                BytesIO(questionnaire),
                "application/json",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["artifacts"] == {
        "logics_json": "logics.json",
        "questionnaire_final": "07_questionnaire_final.json",
    }
    assert body["logics"]["schema"] == "logic_platform.logics.v1"
    assert body["logics"]["rows"][0]["Constraint"] == "MultiSelect"
    run_dir = tmp_path / body["run_id"]
    assert (run_dir / "logics.json").is_file()
    assert not (run_dir / "logics.csv").exists()
    assert not (run_dir / "fairset_structure.json").exists()


def test_structure_from_questionnaire_endpoint_outputs_structure_json(tmp_path):
    app.state.runs_root = tmp_path
    client = TestClient(app)
    questionnaire = b"""{
      "derived_variables": [],
      "questions": [
        {
          "id": "S3",
          "section": "S",
          "text": "Sports followed",
          "type": "multi_select",
          "vars": ["S3r1", "S3r2"],
          "answers": {"S3r1": "Basketball", "S3r2": "Football"},
          "logics": []
        }
      ]
    }"""

    response = client.post(
        "/runs/structure/from-questionnaire",
        data={"project_name": "NBA structure"},
        files={
            "questionnaire_file": (
                "questionnaire_final.json",
                BytesIO(questionnaire),
                "application/json",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["metadata"]["project_name"] == "NBA structure"
    assert body["artifacts"] == {
        "questionnaire_final": "07_questionnaire_final.json",
        "logics_json": "logics.json",
        "structure_json": "structure.json",
        "fairset_constraints": "fairset_constraints.json",
    }
    assert body["structure"]["multiSelect"] == [
        {
            "id": "S3",
            "name": "Sports followed",
            "columns": ["S3r1", "S3r2"],
            "dataType": "LITERAL",
            "contentType": "BINARY_MULTISELECT",
            "shortColumnLabel": [
                {"name": "S3r1", "label": "Basketball"},
                {"name": "S3r2", "label": "Football"},
            ],
        }
    ]
    run_dir = tmp_path / body["run_id"]
    assert (run_dir / "07_questionnaire_final.json").is_file()
    assert (run_dir / "logics.json").is_file()
    assert (run_dir / "structure.json").is_file()


def test_logics_pdf_data_endpoint_runs_pipeline_and_exports_json(monkeypatch, tmp_path):
    app.state.runs_root = tmp_path
    monkeypatch.setattr(api_main, "run_digitization_pipeline", fake_pipeline)
    client = TestClient(app)

    response = client.post(
        "/runs/logics",
        files={
            "questionnaire_pdf": ("survey.pdf", BytesIO(b"%PDF-1.4"), "application/pdf"),
            "data_file": ("data.csv", BytesIO(b"Q1\n1\n"), "text/csv"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["artifacts"] == {
        "logics_json": "logics.json",
        "questionnaire_final": "07_questionnaire_final.json",
    }
    run_dir = tmp_path / body["run_id"]
    assert (run_dir / "inputs" / "questionnaire.pdf").is_file()
    assert (run_dir / "inputs" / "data.csv").is_file()
    assert (run_dir / "logics.json").is_file()
    assert not (run_dir / "logics.csv").exists()


def test_fairset_structure_endpoint_generates_from_logics_json(monkeypatch, tmp_path):
    app.state.runs_root = tmp_path
    monkeypatch.setattr(api_main, "run_digitization_pipeline", fake_pipeline)
    client = TestClient(app)

    run_response = client.post(
        "/runs/logics",
        files={
            "questionnaire_pdf": ("survey.pdf", BytesIO(b"%PDF-1.4"), "application/pdf"),
            "data_file": ("data.csv", BytesIO(b"Q1\n1\n"), "text/csv"),
        },
    )
    run_id = run_response.json()["run_id"]

    response = client.post(f"/runs/{run_id}/fairset-structure")

    assert response.status_code == 200
    body = response.json()
    assert body["artifacts"]["structure_json"] == "structure.json"
    assert body["artifacts"]["fairset_structure"] == "fairset_structure.json"
    assert body["artifacts"]["fairset_constraints"] == "fairset_constraints.json"
    assert body["structure"]["multiSelect"] == [
        {
            "id": "Q1",
            "name": "Choose",
            "columns": ["Q1r1", "Q1r2"],
            "dataType": "LITERAL",
            "contentType": "BINARY_MULTISELECT",
            "shortColumnLabel": [
                {"name": "Q1r1", "label": "Yes"},
                {"name": "Q1r2", "label": "No"},
            ],
        }
    ]
    run_dir = tmp_path / run_id
    assert (run_dir / "structure.json").is_file()
    assert (run_dir / "fairset_structure.json").is_file()
    assert (run_dir / "fairset_constraints.json").is_file()


def test_fairset_review_endpoint_uses_saved_run_data_and_logics(monkeypatch, tmp_path):
    app.state.runs_root = tmp_path
    monkeypatch.setattr(api_main, "run_digitization_pipeline", fake_pipeline)
    client = TestClient(app)

    run_response = client.post(
        "/runs/logics",
        files={
            "questionnaire_pdf": ("survey.pdf", BytesIO(b"%PDF-1.4"), "application/pdf"),
            "data_file": ("data.csv", BytesIO(b"Q1r1,Q1r2\n1,0\n0,1\n"), "text/csv"),
        },
    )
    run_id = run_response.json()["run_id"]

    response = client.post(
        f"/runs/{run_id}/fairset-review",
        files={
            "fairset_file": (
                "fairset.csv",
                BytesIO(b"Q1r1,Q1r2\n1,0\n0,1\n"),
                "text/csv",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["artifacts"]["fairset_report"] == "fairset_report.json"
    assert body["artifacts"]["structure_json"] == "structure.json"
    run_dir = tmp_path / run_id
    assert (run_dir / "fairset_report.json").is_file()
    assert (run_dir / "inputs" / "fairset.csv").is_file()


def test_logics_background_endpoint_exposes_progress(monkeypatch, tmp_path):
    app.state.runs_root = tmp_path
    monkeypatch.setattr(api_main, "run_digitization_pipeline", fake_pipeline)
    client = TestClient(app)

    response = client.post(
        "/runs/logics/start?engine=manus",
        files={
            "questionnaire_pdf": ("survey.pdf", BytesIO(b"%PDF-1.4"), "application/pdf"),
            "data_file": ("data.csv", BytesIO(b"Q1\n1\n"), "text/csv"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert body["progress"]["percent"] >= 5

    progress_response = client.get(f"/runs/{body['run_id']}/progress")
    assert progress_response.status_code == 200
    progress = progress_response.json()
    assert progress["run_id"] == body["run_id"]
    assert progress["status"] in {"running", "complete"}
    assert progress["percent"] >= 5


def test_project_name_defaults_from_request_and_can_be_renamed(monkeypatch, tmp_path):
    app.state.runs_root = tmp_path
    monkeypatch.setattr(api_main, "run_digitization_pipeline", fake_pipeline)
    client = TestClient(app)

    response = client.post(
        "/runs/logics",
        data={"project_name": "NBA"},
        files={
            "questionnaire_pdf": ("survey.pdf", BytesIO(b"%PDF-1.4"), "application/pdf"),
            "data_file": ("nba.csv", BytesIO(b"Q1\n1\n"), "text/csv"),
        },
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    run_response = client.get(f"/runs/{run_id}")
    assert run_response.status_code == 200
    assert run_response.json()["metadata"]["project_name"] == "NBA"

    rename_response = client.patch(f"/runs/{run_id}", json={"project_name": "NBA cleaned"})
    assert rename_response.status_code == 200
    assert rename_response.json()["metadata"]["project_name"] == "NBA cleaned"

    history_response = client.get("/runs")
    assert history_response.status_code == 200
    assert history_response.json()["runs"][0]["metadata"]["project_name"] == "NBA cleaned"


def test_run_history_lists_saved_logics_runs(tmp_path):
    app.state.runs_root = tmp_path
    client = TestClient(app)
    response = client.get("/runs")

    assert response.status_code == 200
    assert response.json() == {"runs": []}
