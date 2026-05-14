"""Run-scoped adapter around the existing survey digitization pipeline."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from logic_platform.artifacts import RunArtifacts


def run_digitization_pipeline(
    pdf_path: Path,
    data_path: Path,
    artifacts: RunArtifacts,
    *,
    engine: str = "opus",
    skip_validation: bool = True,
) -> dict[str, Any]:
    """Run the existing pipeline with all outputs scoped to one run directory."""
    from logic_platform.digitization.orchestrator import run_pipeline

    output_path = artifacts.path("questionnaire_final")
    log_path = artifacts.path("run_log")
    artifacts.append_event(
        {
            "event": "pipeline_started",
            "pdf_path": str(pdf_path),
            "data_path": str(data_path),
            "engine": engine,
            "skip_validation": skip_validation,
            "output_path": str(output_path),
            "intermediate_dir": str(artifacts.run_dir),
        }
    )
    try:
        with log_path.open("a", encoding="utf-8", buffering=1) as log_file:
            with redirect_stdout(log_file), redirect_stderr(log_file):
                result = run_pipeline(
                    str(pdf_path),
                    str(data_path),
                    output_path=str(output_path),
                    save_intermediates=True,
                    show_progress=False,
                    skip_validation=skip_validation,
                    engine=engine,
                    intermediate_dir=str(artifacts.run_dir),
                )
    except Exception as exc:
        artifacts.append_event(
            {
                "event": "pipeline_failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
        )
        raise

    artifacts.append_event(
        {
            "event": "pipeline_completed",
            "questions": len(result.get("questions", [])),
            "derived_variables": len(result.get("derived_variables", [])),
        }
    )
    return result
