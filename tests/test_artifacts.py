import json

import pytest

from logic_platform.artifacts import CANONICAL_ARTIFACTS, RunArtifacts


def test_run_artifacts_use_canonical_names_and_isolated_run_directories(tmp_path):
    run_a = RunArtifacts.create(tmp_path, run_id="survey_a")
    run_b = RunArtifacts.create(tmp_path, run_id="survey_b")

    path_a = run_a.write_json("questionnaire_final", {"ok": True})
    path_b = run_b.write_text("logics_csv", "Target,Source\n")

    assert path_a == tmp_path / "survey_a" / "07_questionnaire_final.json"
    assert path_b == tmp_path / "survey_b" / "logics.csv"
    assert json.loads(path_a.read_text(encoding="utf-8")) == {"ok": True}
    assert path_b.read_text(encoding="utf-8") == "Target,Source\n"
    assert run_a.list_existing() == {"questionnaire_final": path_a}
    assert run_b.list_existing() == {"logics_csv": path_b}


def test_run_artifacts_reject_path_like_run_ids(tmp_path):
    with pytest.raises(ValueError):
        RunArtifacts.create(tmp_path, run_id="../escape")


def test_run_artifacts_reject_unknown_artifact_keys(tmp_path):
    run = RunArtifacts.create(tmp_path, run_id="safe")

    with pytest.raises(KeyError):
        run.path("../../../not_allowed")


def test_write_json_sanitizes_structure_recodings_string_codes(tmp_path):
    """Fairgen legacy often emits codes as a string; disk must always store arrays."""
    run = RunArtifacts.create(tmp_path, run_id="r1")
    path = run.write_json(
        "structure_json",
        {
            "recodings": [
                {
                    "id": "0",
                    "name": "0",
                    "recode": "S2a_Final",
                    "codes": "S2_Final",
                }
            ],
            "multiSelect": [],
            "typeOfNan": [],
        },
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["recodings"][0]["codes"] == ["S2_Final"]
    assert data["recodings"][0]["recode"] == "S2a_Final"


def test_write_json_sanitizes_fairset_constraints_nested_recodings(tmp_path):
    run = RunArtifacts.create(tmp_path, run_id="r2")
    path = run.write_json(
        "fairset_constraints",
        {
            "BF_SS": [],
            "recodings": [
                ["S2_Final", "S2a_Final", "SS", "", True],
                {"id": "0", "name": "0", "recode": "S2a_Final", "codes": "S2_Final"},
            ],
            "extra": {"recodings": [{"recode": "T", "codes": "SRC"}]},
        },
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["recodings"][0] == ["S2_Final", "S2a_Final", "SS", "", True]
    assert data["recodings"][1]["codes"] == ["S2_Final"]
    assert data["extra"]["recodings"][0]["codes"] == ["SRC"]


def test_fairset_report_legacy_json_lists_and_prefers_csv_when_both_exist(tmp_path):
    run = RunArtifacts.create(tmp_path, run_id="legacy_run")
    run.run_dir.mkdir(parents=True, exist_ok=True)
    legacy_path = run.run_dir / "fairset_report.json"
    legacy_path.write_text('{"entries": []}', encoding="utf-8")

    listed = run.list_existing()
    assert listed["fairset_report"] == legacy_path
    assert listed["fairset_report_json"] == legacy_path
    assert run.existing_path("fairset_report") == legacy_path

    csv_path = run.run_dir / "fairset_report.csv"
    csv_path.write_text("Section,Question\n", encoding="utf-8")

    listed2 = run.list_existing()
    assert listed2["fairset_report"] == csv_path
    assert listed2["fairset_report_json"] == legacy_path.parent / "fairset_report.json"
    assert run.existing_path("fairset_report") == csv_path


def test_canonical_artifacts_match_refactor_plan_names():
    assert CANONICAL_ARTIFACTS == {
        "pdf_structure": "01_pdf_structure.json",
        "dataset_inventory": "02_dataset_inventory.json",
        "mapping": "03_mapping.json",
        "resolution": "04_resolution.json",
        "pattern_report": "05_pattern_report.json",
        "logic": "06_logic.json",
        "questionnaire_final": "07_questionnaire_final.json",
        "validation_report": "08_validation_report.json",
        "run_log": "run.log",
        "events_log": "events.jsonl",
        "logics_csv": "logics.csv",
        "logics_json": "logics.json",
        "fairset_constraints": "fairset_constraints.json",
        "structure_json": "structure.json",
        "fairset_structure": "fairset_structure.json",
        "fairset_report": "fairset_report.csv",
        "fairset_report_json": "fairset_report.json",
        "fairset_report_xlsx": "fairset_report.xlsx",
    }
