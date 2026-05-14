from io import BytesIO
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402


def test_transform_logics_csv_endpoint_writes_run_artifacts(tmp_path):
    app.state.runs_root = tmp_path
    client = TestClient(app)
    csv_bytes = (
        "Target,Source,Constraint,B/F Relationship,Comment,Is Implemented,Custom Query,ID\n"
        "Q2,Q1,Block/Force,Single to Single,Q2 depends on Q1,Yes,,1\n"
        "\"['Q3r1', 'Q3r2']\",,MultiSelect,Single to Multi,Q3 group,Yes,,2\n"
    ).encode("utf-8")

    response = client.post(
        "/runs/transform",
        files={"logics_file": ("logics.csv", BytesIO(csv_bytes), "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    run_dir = tmp_path / body["run_id"]
    assert (run_dir / "fairset_constraints.json").is_file()
    assert (run_dir / "structure.json").is_file()
    assert (run_dir / "fairset_structure.json").is_file()
    assert body["constraints"]["BF_SS"] == [
        ["Q1", "Q2", "Q2 depends on Q1", "block_force", True]
    ]
    assert body["structure"]["multiSelect"] == [
        {
            "id": "Q3",
            "name": "Q3 group",
            "columns": ["Q3r1", "Q3r2"],
            "dataType": "LITERAL",
            "contentType": "BINARY_MULTISELECT",
            "shortColumnLabel": [
                {"name": "Q3r1", "label": "Q3r1"},
                {"name": "Q3r2", "label": "Q3r2"},
            ],
        }
    ]

    status_response = client.get(f"/runs/{body['run_id']}")
    assert status_response.status_code == 200
    assert status_response.json()["artifacts"] == {
        "fairset_constraints": "fairset_constraints.json",
        "structure_json": "structure.json",
        "fairset_structure": "fairset_structure.json",
    }

    download_response = client.get(
        f"/runs/{body['run_id']}/artifacts/structure_json"
    )
    assert download_response.status_code == 200
    assert download_response.json() == body["structure"]


def test_transform_logics_csv_endpoint_rejects_non_csv_files():
    app.state.runs_root = None
    client = TestClient(app)

    response = client.post(
        "/runs/transform",
        files={"logics_file": ("logics.txt", BytesIO(b"not,csv"), "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "logics_file must be a CSV file"


def test_download_structure_json_coerces_legacy_string_codes(tmp_path):
    """On-disk legacy runs may have scalar codes; downloads must still be normalized."""
    app.state.runs_root = tmp_path
    client = TestClient(app)
    run_dir = tmp_path / "legacy_run"
    run_dir.mkdir(parents=True)
    legacy = {
        "recodings": [
            {"id": "0", "name": "0", "recode": "S2a_Final", "codes": "S2_Final"},
        ],
        "multiSelect": [],
        "typeOfNan": [],
    }
    (run_dir / "structure.json").write_text(json.dumps(legacy), encoding="utf-8")

    download = client.get("/runs/legacy_run/artifacts/structure_json")
    assert download.status_code == 200
    data = download.json()
    assert data["recodings"][0]["codes"] == ["S2_Final"]
    assert data["recodings"][0]["recode"] == "S2a_Final"


def test_download_fairset_constraints_coerces_mixed_legacy_recodings(tmp_path):
    app.state.runs_root = tmp_path
    client = TestClient(app)
    run_dir = tmp_path / "constraints_run"
    run_dir.mkdir(parents=True)
    legacy_constraints = {
        "recodings": [
            ["SRC", "TGT", "SS", "", True],
            {"id": "0", "name": "0", "recode": "S2a_Final", "codes": "S2_Final"},
        ],
        "nested": {"recodings": [{"recode": "X", "codes": "OLD"}]},
    }
    (run_dir / "fairset_constraints.json").write_text(json.dumps(legacy_constraints), encoding="utf-8")

    download = client.get("/runs/constraints_run/artifacts/fairset_constraints")
    assert download.status_code == 200
    body = download.json()
    assert body["recodings"][1]["codes"] == ["S2_Final"]
    assert body["nested"]["recodings"][0]["codes"] == ["OLD"]


def test_download_artifact_rejects_unknown_run_or_artifact(tmp_path):
    app.state.runs_root = tmp_path
    client = TestClient(app)

    missing_run = client.get("/runs/not-there")
    missing_artifact = client.get("/runs/not-there/artifacts/fairset_structure")

    assert missing_run.status_code == 404
    assert missing_artifact.status_code == 404
