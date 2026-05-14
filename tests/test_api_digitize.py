from io import BytesIO

from fastapi.testclient import TestClient

import apps.api.main as api_main
from apps.api.main import app


def fake_pipeline(pdf_path, data_path, artifacts, *, engine="manus", skip_validation=True):
    assert pdf_path.name == "questionnaire.pdf"
    assert data_path.name == "data.csv"
    assert artifacts.run_dir.name
    assert engine == "manus"
    assert skip_validation is True
    questionnaire = {
        "derived_variables": [],
        "questions": [
            {
                "id": "Q1",
                "section": "S",
                "text": "Select all",
                "type": "multi_select",
                "vars": ["Q1r1", "Q1r2"],
                "answers": {},
                "logics": [],
            }
        ],
    }
    artifacts.write_json("questionnaire_final", questionnaire)
    return questionnaire


def test_pdf_data_logics_endpoint_runs_pipeline_and_exports_logics_json(monkeypatch, tmp_path):
    app.state.runs_root = tmp_path
    monkeypatch.setattr(api_main, "run_digitization_pipeline", fake_pipeline)
    client = TestClient(app)

    response = client.post(
        "/runs/logics",
        files={
            "questionnaire_pdf": ("questionnaire.pdf", BytesIO(b"%PDF-1.4"), "application/pdf"),
            "data_file": ("dataset.csv", BytesIO(b"Q1r1,Q1r2\n1,\n"), "text/csv"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    run_dir = tmp_path / body["run_id"]
    assert body["status"] == "complete"
    assert set(body["artifacts"]) == {"logics_json", "questionnaire_final"}
    assert (run_dir / "inputs" / "questionnaire.pdf").is_file()
    assert (run_dir / "inputs" / "data.csv").is_file()
    assert (run_dir / "07_questionnaire_final.json").is_file()
    assert (run_dir / "logics.json").is_file()
    assert (run_dir / "events.jsonl").is_file()
    assert not (run_dir / "logics.csv").exists()
    assert not (run_dir / "fairset_structure.json").exists()
    assert body["logics"]["row_count"] == 1
    assert body["logics"]["rows"][0]["Constraint"] == "MultiSelect"


def test_regenerate_logics_from_saved_questionnaire_history(tmp_path):
    app.state.runs_root = tmp_path
    run_dir = tmp_path / "saved"
    run_dir.mkdir()
    (run_dir / "07_questionnaire_final.json").write_text(
        """
        {
          "derived_variables": [],
          "questions": [
            {
              "id": "Q1",
              "section": "A",
              "text": "Question",
              "type": "single_select",
              "vars": ["Q1"],
              "answers": {},
              "logics": []
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    client = TestClient(app)

    response = client.post("/runs/saved/logics")

    assert response.status_code == 200
    assert response.json()["artifacts"] == {"logics_json": "logics.json"}
    assert not (run_dir / "logics.csv").exists()
    assert (run_dir / "logics.json").is_file()


def test_digitize_endpoint_rejects_non_pdf_questionnaire(tmp_path):
    app.state.runs_root = tmp_path
    client = TestClient(app)

    response = client.post(
        "/runs/logics",
        files={
            "questionnaire_pdf": ("questionnaire.txt", BytesIO(b"bad"), "text/plain"),
            "data_file": ("dataset.csv", BytesIO(b"Q1\n1\n"), "text/csv"),
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "questionnaire_pdf must be a PDF file"
