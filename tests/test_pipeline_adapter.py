from pathlib import Path

import logic_platform.digitization.pipeline as pipeline
from logic_platform.artifacts import RunArtifacts


def test_run_digitization_pipeline_scopes_existing_pipeline_to_run_dir(monkeypatch, tmp_path):
    calls = {}

    def fake_run_pipeline(
        pdf_path,
        dataset_path,
        *,
        output_path,
        save_intermediates,
        show_progress,
        skip_validation,
        engine,
        intermediate_dir,
    ):
        calls.update(
            {
                "pdf_path": pdf_path,
                "dataset_path": dataset_path,
                "output_path": output_path,
                "save_intermediates": save_intermediates,
                "show_progress": show_progress,
                "skip_validation": skip_validation,
                "engine": engine,
                "intermediate_dir": intermediate_dir,
            }
        )
        return {"derived_variables": [], "questions": []}

    import logic_platform.digitization.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "run_pipeline", fake_run_pipeline)
    artifacts = RunArtifacts.create(tmp_path, run_id="pipeline")
    pdf = tmp_path / "q.pdf"
    data = tmp_path / "data.csv"

    result = pipeline.run_digitization_pipeline(pdf, data, artifacts, engine="manus")

    assert result == {"derived_variables": [], "questions": []}
    assert (tmp_path / "pipeline" / "run.log").is_file()
    assert (tmp_path / "pipeline" / "events.jsonl").is_file()
    assert calls == {
        "pdf_path": str(pdf),
        "dataset_path": str(data),
        "output_path": str(tmp_path / "pipeline" / "07_questionnaire_final.json"),
        "save_intermediates": True,
        "show_progress": False,
        "skip_validation": True,
        "engine": "manus",
        "intermediate_dir": str(tmp_path / "pipeline"),
    }
