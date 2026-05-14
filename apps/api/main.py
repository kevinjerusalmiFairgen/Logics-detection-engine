"""FastAPI app for the local logic platform."""

from __future__ import annotations

from io import BytesIO
import json
import logging
import os
from pathlib import Path
import tempfile

import pandas as pd
import pyreadstat
from fastapi import BackgroundTasks, Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from logic_platform.artifacts import (
    RECODING_SCRUB_ARTIFACT_KEYS,
    RunArtifacts,
    sanitize_recoding_artifact,
)
from logic_platform.digitization.logics_export import export_logics_json_from_questionnaire
from logic_platform.digitization.pipeline import run_digitization_pipeline
from logic_platform.fairset.streamlit_compat import prior_file_extract
from logic_platform.fairset.structure import (
    coerce_recodings_deep,
    coerce_structure_recodings,
    normalize_structure,
)
from logic_platform.fairset.validator import run_review_from_dataframes
from logic_platform.progress import build_run_progress


logging.basicConfig(
    level=os.getenv("LOGIC_PLATFORM_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("logic_platform.api")
load_dotenv()

_env_web_dist = os.getenv("LOGIC_PLATFORM_WEB_DIST")
if _env_web_dist and _env_web_dist.strip():
    _WEB_DIST = Path(_env_web_dist).expanduser().resolve()
else:
    _WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
_WEB_INDEX = _WEB_DIST / "index.html"

_NO_UI_FALLBACK = """<!DOCTYPE html>
<html lang="en">
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Logic Platform</title>
<body style="font-family:system-ui,sans-serif;max-width:36rem;margin:2rem auto;line-height:1.5;color:#142">
<h1 style="font-weight:600">Logic Platform</h1>
<p>The API is running, but the web UI bundle is missing on this server.</p>
<p><strong>To use the UI here</strong> (<code>http://127.0.0.1:8000</code>):</p>
<pre style="background:#f4f4f5;padding:12px;border-radius:8px;font-size:13px">cd apps/web
npm install && npm run build</pre>
<p>Then restart uvicorn. Alternatively run the dev UI: <code>npm run dev</code> → open the URL it prints (often <code>http://127.0.0.1:5173</code>).</p>
<p><a href="/docs">API docs (/docs)</a> · <a href="/runs">GET /runs</a></p>
</body></html>
"""

app = FastAPI(title="Logic Platform API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_model=None)
def root_page() -> FileResponse | HTMLResponse:
    """Serve the built SPA when `apps/web/dist` exists; otherwise show build instructions."""
    if _WEB_INDEX.is_file():
        return FileResponse(_WEB_INDEX)
    return HTMLResponse(_NO_UI_FALLBACK)


def get_runs_root() -> Path:
    configured = getattr(app.state, "runs_root", None)
    if configured is not None:
        return Path(configured)
    return Path(os.getenv("LOGIC_PLATFORM_RUNS_ROOT", "runs"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


async def read_csv_upload(upload: UploadFile, label: str) -> pd.DataFrame:
    if not (upload.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail=f"{label} must be a CSV file")
    content = await upload.read()
    try:
        return pd.read_csv(BytesIO(content))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label}: {exc}") from exc


async def read_json_upload(upload: UploadFile, label: str) -> dict:
    if not (upload.filename or "").lower().endswith(".json"):
        raise HTTPException(status_code=400, detail=f"{label} must be a JSON file")
    content = await upload.read()
    try:
        parsed = json.loads(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail=f"{label} must contain a JSON object")
    return parsed


async def read_tabular_upload(upload: UploadFile, label: str) -> pd.DataFrame:
    filename = upload.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in {".sav", ".csv", ".xlsx", ".xls"}:
        raise HTTPException(
            status_code=400,
            detail=f"{label} must be one of .sav, .csv, .xlsx, or .xls",
        )
    content = await upload.read()
    try:
        return _read_tabular_bytes(content, suffix)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label}: {exc}") from exc


def _read_tabular_bytes(content: bytes, suffix: str) -> pd.DataFrame:
    if suffix == ".csv":
        return pd.read_csv(BytesIO(content))
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(BytesIO(content))
    if suffix == ".sav":
        with tempfile.NamedTemporaryFile(suffix=".sav") as tmp:
            tmp.write(content)
            tmp.flush()
            df, _ = pyreadstat.read_sav(tmp.name)
        return df
    raise ValueError(f"Unsupported format: {suffix}")


def _read_tabular_path(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".sav":
        df, _ = pyreadstat.read_sav(str(path))
        return df
    raise ValueError(f"Unsupported format: {suffix}")


def _artifact_response(artifacts: RunArtifacts, keys: list[str]) -> dict[str, str]:
    return {key: artifacts.path(key).name for key in keys}


def _run_metadata(artifacts: RunArtifacts) -> dict[str, str]:
    events_path = artifacts.path("events_log")
    if not events_path.is_file():
        return {}
    metadata: dict[str, str] = {}
    for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") in {
            "run_created",
            "logics_from_questionnaire_started",
            "questionnaire_structure_started",
        }:
            metadata.update(
                {
                    key: value
                    for key, value in {
                        "project_name": event.get("project_name"),
                        "pdf_filename": event.get("pdf_filename"),
                        "data_filename": event.get("data_filename"),
                        "filename": event.get("filename"),
                        "engine": event.get("engine"),
                    }.items()
                    if value
                }
            )
        if event.get("event") == "project_renamed" and event.get("project_name"):
            metadata["project_name"] = event["project_name"]
    return metadata


def _generate_fairset_structure_from_logics(artifacts: RunArtifacts) -> dict:
    logics_path = artifacts.path("logics_json")
    if not logics_path.is_file():
        raise HTTPException(status_code=404, detail="logics.json not found for this run")

    with logics_path.open(encoding="utf-8") as f:
        logics = json.load(f)
    rows = logics.get("rows", [])
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="logics.json rows must be a list")

    prior_df = pd.DataFrame(rows)
    constraints, raw_structure = prior_file_extract(prior_df)
    structure = normalize_structure(
        raw_structure,
        prior_df=prior_df,
        questionnaire=_questionnaire_from_run(artifacts),
    )
    artifacts.write_json("structure_json", structure)
    artifacts.write_json("fairset_structure", structure)
    artifacts.write_json("fairset_constraints", constraints)
    artifacts.append_event(
        {
            "event": "fairset_structure_generated_from_logics_json",
            "recodings": len(structure.get("recodings", [])),
            "multiSelect": len(structure.get("multiSelect", [])),
            "typeOfNan": len(structure.get("typeOfNan", [])),
            "warnings": 0,
        }
    )
    return {
        "run_id": artifacts.run_id,
        "status": "complete",
        "warnings": [],
        "artifacts": _artifact_response(
            artifacts,
            ["structure_json", "fairset_structure", "fairset_constraints", "logics_json"],
        ),
        "structure": coerce_structure_recodings(structure),
        "constraints": coerce_recodings_deep(constraints),
    }


def _write_questionnaire_structure_run(
    questionnaire: dict,
    *,
    filename: str | None,
    project_name: str | None = None,
) -> dict:
    export = export_logics_json_from_questionnaire(questionnaire)
    prior_df = pd.DataFrame(export.payload["rows"])
    constraints, raw_structure = prior_file_extract(prior_df)
    structure = normalize_structure(
        raw_structure,
        prior_df=prior_df,
        questionnaire=questionnaire,
    )

    artifacts = RunArtifacts.create(get_runs_root(), run_id=None)
    artifacts.append_event(
        {
            "event": "questionnaire_structure_started",
            "project_name": project_name,
            "filename": filename,
            "question_count": len(questionnaire.get("questions", [])),
        }
    )
    artifacts.write_json("questionnaire_final", questionnaire)
    artifacts.write_json("logics_json", export.payload)
    artifacts.write_json("structure_json", structure)
    artifacts.write_json("fairset_structure", structure)
    artifacts.write_json("fairset_constraints", constraints)
    artifacts.append_event(
        {
            "event": "questionnaire_structure_completed",
            "row_count": export.payload["row_count"],
            "multiSelect": len(structure.get("multiSelect", [])),
            "recodings": len(structure.get("recodings", [])),
        }
    )
    return {
        "run_id": artifacts.run_id,
        "status": "complete",
        "artifacts": _artifact_response(
            artifacts,
            ["questionnaire_final", "logics_json", "structure_json", "fairset_constraints"],
        ),
        "metadata": _run_metadata(artifacts),
        "logics": export.payload,
        "structure": coerce_structure_recodings(structure),
        "constraints": coerce_recodings_deep(constraints),
    }


def _saved_data_file(artifacts: RunArtifacts) -> Path:
    input_dir = artifacts.run_dir / "inputs"
    if not input_dir.is_dir():
        raise HTTPException(status_code=404, detail="Saved run inputs not found")
    candidates = [
        path
        for path in input_dir.iterdir()
        if path.name.startswith("data") and path.suffix.lower() in {".sav", ".csv", ".xlsx", ".xls"}
    ]
    if not candidates:
        raise HTTPException(status_code=404, detail="Saved data file not found for this run")
    return candidates[0]


def _logics_dataframe_from_run(artifacts: RunArtifacts) -> pd.DataFrame:
    logics_path = artifacts.path("logics_json")
    if not logics_path.is_file():
        raise HTTPException(status_code=404, detail="logics.json not found for this run")
    with logics_path.open(encoding="utf-8") as f:
        logics = json.load(f)
    rows = logics.get("rows", [])
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="logics.json rows must be a list")
    return pd.DataFrame(rows)


def _questionnaire_from_run(artifacts: RunArtifacts) -> dict | None:
    questionnaire_path = artifacts.path("questionnaire_final")
    if not questionnaire_path.is_file():
        return None
    with questionnaire_path.open(encoding="utf-8") as f:
        questionnaire = json.load(f)
    return questionnaire if isinstance(questionnaire, dict) else None


def _validate_logics_uploads(
    questionnaire_pdf: UploadFile,
    data_file: UploadFile,
    engine: str,
) -> None:
    if not (questionnaire_pdf.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="questionnaire_pdf must be a PDF file")
    if engine not in {"opus", "manus"}:
        raise HTTPException(status_code=400, detail="engine must be 'opus' or 'manus'")
    data_name = (data_file.filename or "").lower()
    if not data_name.endswith((".sav", ".csv", ".xlsx", ".xls")):
        raise HTTPException(
            status_code=400,
            detail="data_file must be one of .sav, .csv, .xlsx, or .xls",
        )


async def _create_logics_artifacts(
    questionnaire_pdf: UploadFile,
    data_file: UploadFile,
    engine: str,
    skip_validation: bool,
    project_name: str | None,
) -> tuple[RunArtifacts, Path, Path]:
    artifacts = RunArtifacts.create(get_runs_root(), run_id=None)
    artifacts.append_event(
        {
            "event": "run_created",
            "project_name": project_name,
            "pdf_filename": questionnaire_pdf.filename,
            "data_filename": data_file.filename,
            "engine": engine,
            "skip_validation": skip_validation,
        }
    )
    input_dir = artifacts.ensure() / "inputs"
    input_dir.mkdir(exist_ok=True)
    pdf_path = input_dir / "questionnaire.pdf"
    data_suffix = Path(data_file.filename or "data").suffix or ".data"
    data_path = input_dir / f"data{data_suffix}"
    pdf_path.write_bytes(await questionnaire_pdf.read())
    data_path.write_bytes(await data_file.read())
    artifacts.append_event(
        {
            "event": "inputs_saved",
            "questionnaire_pdf": str(pdf_path.relative_to(artifacts.run_dir)),
            "data_file": str(data_path.relative_to(artifacts.run_dir)),
            "pdf_bytes": pdf_path.stat().st_size,
            "data_bytes": data_path.stat().st_size,
        }
    )
    return artifacts, pdf_path, data_path


def _execute_logics_pipeline(
    artifacts: RunArtifacts,
    pdf_path: Path,
    data_path: Path,
    *,
    engine: str,
    skip_validation: bool,
) -> dict:
    try:
        questionnaire = run_digitization_pipeline(
            pdf_path,
            data_path,
            artifacts,
            engine=engine,
            skip_validation=skip_validation,
        )
        export = export_logics_json_from_questionnaire(questionnaire)
        artifacts.write_json("logics_json", export.payload)
        artifacts.append_event(
            {
                "event": "logics_json_written",
                "row_count": export.payload["row_count"],
                "artifact": artifacts.path("logics_json").name,
            }
        )
    except Exception as exc:
        logger.exception("Pipeline failed run_id=%s", artifacts.run_id)
        failure = {
            "status": "failed",
            "message": str(exc),
            "inputs": {
                "questionnaire_pdf": str(pdf_path.relative_to(artifacts.run_dir)),
                "data_file": str(data_path.relative_to(artifacts.run_dir)),
            },
            "outputs": ["logics_json"],
        }
        artifacts.write_json("validation_report", failure)
        raise

    logger.info(
        "Completed PDF+data logics run run_id=%s rows=%s",
        artifacts.run_id,
        export.payload["row_count"],
    )
    return {
        "run_id": artifacts.run_id,
        "status": "complete",
        "inputs": {
            "questionnaire_pdf": str(pdf_path.relative_to(artifacts.run_dir)),
            "data_file": str(data_path.relative_to(artifacts.run_dir)),
        },
        "artifacts": _artifact_response(artifacts, ["logics_json", "questionnaire_final"]),
        "logics": export.payload,
    }


def _execute_logics_pipeline_background(
    artifacts: RunArtifacts,
    pdf_path: Path,
    data_path: Path,
    *,
    engine: str,
    skip_validation: bool,
) -> None:
    try:
        _execute_logics_pipeline(
            artifacts,
            pdf_path,
            data_path,
            engine=engine,
            skip_validation=skip_validation,
        )
    except Exception:
        # The progress endpoint reports failures from events.jsonl and validation_report.
        return


@app.get("/runs")
def list_runs() -> dict:
    root = get_runs_root()
    logger.info("Listing runs from root=%s", root)
    if not root.is_dir():
        return {"runs": []}
    runs = []
    for run_dir in sorted(root.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        artifacts = RunArtifacts.create(root, run_id=run_dir.name)
        runs.append(
            {
                "run_id": run_dir.name,
                "artifacts": {
                    key: path.name for key, path in artifacts.list_existing().items()
                },
                "metadata": _run_metadata(artifacts),
            }
        )
    return {"runs": runs}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    logger.info("Fetching run status run_id=%s", run_id)
    artifacts = RunArtifacts.create(get_runs_root(), run_id=run_id)
    existing = artifacts.list_existing()
    if not artifacts.run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "run_id": run_id,
        "artifacts": {key: path.name for key, path in existing.items()},
        "metadata": _run_metadata(artifacts),
        "progress": build_run_progress(artifacts),
    }


@app.patch("/runs/{run_id}")
def update_run_metadata(run_id: str, payload: dict = Body(...)) -> dict:
    logger.info("Updating run metadata run_id=%s", run_id)
    artifacts = RunArtifacts.create(get_runs_root(), run_id=run_id)
    if not artifacts.run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Run not found")

    project_name = str(payload.get("project_name", "")).strip()
    if not project_name:
        raise HTTPException(status_code=400, detail="project_name is required")
    if len(project_name) > 120:
        raise HTTPException(status_code=400, detail="project_name must be 120 characters or fewer")

    artifacts.append_event({"event": "project_renamed", "project_name": project_name})
    return {
        "run_id": run_id,
        "artifacts": {key: path.name for key, path in artifacts.list_existing().items()},
        "metadata": _run_metadata(artifacts),
        "progress": build_run_progress(artifacts),
    }


@app.get("/runs/{run_id}/progress")
def get_run_progress(run_id: str) -> dict:
    logger.info("Fetching run progress run_id=%s", run_id)
    artifacts = RunArtifacts.create(get_runs_root(), run_id=run_id)
    if not artifacts.run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Run not found")
    return build_run_progress(artifacts)


@app.get("/runs/{run_id}/artifacts/{artifact_key}", response_model=None)
def download_artifact(run_id: str, artifact_key: str) -> FileResponse | Response:
    logger.info("Downloading artifact run_id=%s artifact_key=%s", run_id, artifact_key)
    try:
        artifacts = RunArtifacts.create(get_runs_root(), run_id=run_id)
        path = artifacts.path(artifact_key)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc

    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact_key in RECODING_SCRUB_ARTIFACT_KEYS:
        try:
            with path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail="Artifact is not valid JSON") from exc
        payload = sanitize_recoding_artifact(artifact_key, payload)
        encoded = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        return Response(
            content=encoded,
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
        )

    return FileResponse(path, filename=path.name)


@app.post("/runs/logics/from-questionnaire")
async def logics_from_questionnaire_json(questionnaire_file: UploadFile = File(...)) -> dict:
    """Generate logics.json from saved final questionnaire JSON."""
    logger.info("Generating logics JSON from questionnaire filename=%s", questionnaire_file.filename)
    questionnaire = await read_json_upload(questionnaire_file, "questionnaire_file")
    export = export_logics_json_from_questionnaire(questionnaire)

    artifacts = RunArtifacts.create(get_runs_root(), run_id=None)
    artifacts.append_event(
        {
            "event": "logics_from_questionnaire_started",
            "filename": questionnaire_file.filename,
            "question_count": len(questionnaire.get("questions", [])),
        }
    )
    artifacts.write_json("questionnaire_final", questionnaire)
    artifacts.write_json("logics_json", export.payload)
    artifacts.append_event(
        {
            "event": "logics_from_questionnaire_completed",
            "row_count": export.payload["row_count"],
        }
    )
    logger.info(
        "Generated logics JSON run_id=%s rows=%s",
        artifacts.run_id,
        export.payload["row_count"],
    )

    return {
        "run_id": artifacts.run_id,
        "status": "complete",
        "artifacts": _artifact_response(artifacts, ["logics_json", "questionnaire_final"]),
        "logics": export.payload,
    }


@app.post("/runs/structure/from-questionnaire")
async def structure_from_questionnaire_json(
    questionnaire_file: UploadFile = File(...),
    project_name: str | None = Form(None),
) -> dict:
    """Generate structure.json directly from a saved final questionnaire JSON."""
    logger.info("Generating structure JSON from questionnaire filename=%s", questionnaire_file.filename)
    questionnaire = await read_json_upload(questionnaire_file, "questionnaire_file")
    return _write_questionnaire_structure_run(
        questionnaire,
        filename=questionnaire_file.filename,
        project_name=project_name,
    )


@app.post("/runs/{run_id}/logics")
def regenerate_logics_json_from_history(run_id: str) -> dict:
    """Regenerate logics.json from a saved questionnaire_final artifact."""
    logger.info("Regenerating logics JSON from history run_id=%s", run_id)
    artifacts = RunArtifacts.create(get_runs_root(), run_id=run_id)
    questionnaire_path = artifacts.path("questionnaire_final")
    if not questionnaire_path.is_file():
        raise HTTPException(status_code=404, detail="Saved questionnaire JSON not found")

    with questionnaire_path.open(encoding="utf-8") as f:
        questionnaire = json.load(f)
    export = export_logics_json_from_questionnaire(questionnaire)
    artifacts.write_json("logics_json", export.payload)
    artifacts.append_event(
        {
            "event": "logics_regenerated_from_history",
            "row_count": export.payload["row_count"],
        }
    )
    return {
        "run_id": run_id,
        "status": "complete",
        "artifacts": _artifact_response(artifacts, ["logics_json"]),
        "logics": export.payload,
    }


@app.post("/runs/{run_id}/fairset-structure")
def generate_fairset_structure_from_history(run_id: str) -> dict:
    """Generate Fairset structure/constraints JSON from a saved logics.json artifact."""
    logger.info("Generating Fairset structure from history run_id=%s", run_id)
    artifacts = RunArtifacts.create(get_runs_root(), run_id=run_id)
    if not artifacts.run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Run not found")
    return _generate_fairset_structure_from_logics(artifacts)


@app.post("/runs/{run_id}/fairset-review")
async def review_fairset_from_history(run_id: str, fairset_file: UploadFile = File(...)) -> dict:
    """Review an uploaded Fairset against the data/logics saved in a previous run."""
    logger.info("Reviewing Fairset from history run_id=%s fairset=%s", run_id, fairset_file.filename)
    artifacts = RunArtifacts.create(get_runs_root(), run_id=run_id)
    if not artifacts.run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        train_df = _read_tabular_path(_saved_data_file(artifacts))
        fairset_df = await read_tabular_upload(fairset_file, "fairset_file")
        prior_df = _logics_dataframe_from_run(artifacts)
        result = run_review_from_dataframes(
            prior_df,
            train_df,
            fairset_df,
            questionnaire=_questionnaire_from_run(artifacts),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    input_dir = artifacts.ensure() / "inputs"
    input_dir.mkdir(exist_ok=True)
    fairset_suffix = Path(fairset_file.filename or "fairset").suffix or ".data"
    fairset_path = input_dir / f"fairset{fairset_suffix}"
    await fairset_file.seek(0)
    fairset_path.write_bytes(await fairset_file.read())

    artifacts.write_json("fairset_constraints", result.constraints)
    artifacts.write_json("structure_json", result.structure)
    artifacts.write_json("fairset_structure", result.structure)
    artifacts.write_json("fairset_report", result.report)
    artifacts.append_event(
        {
            "event": "fairset_review_completed",
            "fairset_filename": fairset_file.filename,
            "report_rows": len(result.report),
            "missing_columns": len(result.missing_columns),
            "warnings": len(result.warnings),
        }
    )

    return {
        "run_id": run_id,
        "status": "complete" if not result.missing_columns else "missing_columns",
        "missing_columns": result.missing_columns,
        "warnings": result.warnings,
        "artifacts": _artifact_response(
            artifacts,
            ["fairset_report", "structure_json", "fairset_constraints", "logics_json"],
        ),
        "report": result.report,
    }


@app.post("/runs/logics")
async def create_logics_run(
    questionnaire_pdf: UploadFile = File(...),
    data_file: UploadFile = File(...),
    engine: str = "manus",
    skip_validation: bool = True,
    project_name: str | None = Form(None),
) -> dict:
    """Run PDF + data extraction and return the generated logics JSON."""
    logger.info(
        "Starting PDF+data logics run pdf=%s data=%s engine=%s skip_validation=%s",
        questionnaire_pdf.filename,
        data_file.filename,
        engine,
        skip_validation,
    )
    _validate_logics_uploads(questionnaire_pdf, data_file, engine)
    artifacts, pdf_path, data_path = await _create_logics_artifacts(
        questionnaire_pdf,
        data_file,
        engine,
        skip_validation,
        project_name,
    )
    try:
        return _execute_logics_pipeline(
            artifacts,
            pdf_path,
            data_path,
            engine=engine,
            skip_validation=skip_validation,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {exc}") from exc

@app.post("/runs/logics/start")
async def start_logics_run(
    background_tasks: BackgroundTasks,
    questionnaire_pdf: UploadFile = File(...),
    data_file: UploadFile = File(...),
    engine: str = "manus",
    skip_validation: bool = True,
    project_name: str | None = Form(None),
) -> dict:
    """Start PDF + data extraction in the background and return immediately."""
    logger.info(
        "Starting background PDF+data logics run pdf=%s data=%s engine=%s skip_validation=%s",
        questionnaire_pdf.filename,
        data_file.filename,
        engine,
        skip_validation,
    )
    _validate_logics_uploads(questionnaire_pdf, data_file, engine)
    artifacts, pdf_path, data_path = await _create_logics_artifacts(
        questionnaire_pdf,
        data_file,
        engine,
        skip_validation,
        project_name,
    )
    background_tasks.add_task(
        _execute_logics_pipeline_background,
        artifacts,
        pdf_path,
        data_path,
        engine=engine,
        skip_validation=skip_validation,
    )
    return {
        "run_id": artifacts.run_id,
        "status": "running",
        "artifacts": _artifact_response(artifacts, ["run_log", "events_log"]),
        "metadata": _run_metadata(artifacts),
        "progress": build_run_progress(artifacts),
    }


@app.post("/runs/transform")
async def transform_logics_csv(logics_file: UploadFile = File(...)) -> dict:
    """Transform a logics CSV into Fairset constraints and structure JSON."""
    logger.info("Legacy transform endpoint called filename=%s", logics_file.filename)
    prior_df = await read_csv_upload(logics_file, "logics_file")
    try:
        constraints, raw_structure = prior_file_extract(prior_df)
        structure = normalize_structure(raw_structure, prior_df=prior_df)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    artifacts = RunArtifacts.create(get_runs_root(), run_id=None)
    constraints_path = artifacts.write_json("fairset_constraints", constraints)
    structure_json_path = artifacts.write_json("structure_json", structure)
    structure_path = artifacts.write_json("fairset_structure", structure)

    return {
        "run_id": artifacts.run_id,
        "warnings": [],
        "artifacts": {
            "fairset_constraints": constraints_path.name,
            "structure_json": structure_json_path.name,
            "fairset_structure": structure_path.name,
        },
        "constraints": coerce_recodings_deep(constraints),
        "structure": coerce_structure_recodings(structure),
    }


@app.post("/runs/review")
async def review_fairset(
    train_file: UploadFile = File(...),
    fairset_file: UploadFile = File(...),
    logics_file: UploadFile = File(...),
) -> dict:
    """Run a headless Fairset review from train/fairset/logics CSV inputs."""
    logger.info(
        "Legacy fairset review endpoint called train=%s fairset=%s logics=%s",
        train_file.filename,
        fairset_file.filename,
        logics_file.filename,
    )
    train_df = await read_csv_upload(train_file, "train_file")
    fairset_df = await read_csv_upload(fairset_file, "fairset_file")
    prior_df = await read_csv_upload(logics_file, "logics_file")

    try:
        result = run_review_from_dataframes(prior_df, train_df, fairset_df)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    artifacts = RunArtifacts.create(get_runs_root(), run_id=None)
    constraints_path = artifacts.write_json("fairset_constraints", result.constraints)
    structure_path = artifacts.write_json("fairset_structure", result.structure)
    report_path = artifacts.write_json("fairset_report", result.report)

    return {
        "run_id": artifacts.run_id,
        "missing_columns": result.missing_columns,
        "warnings": result.warnings,
        "artifacts": {
            "fairset_constraints": constraints_path.name,
            "fairset_structure": structure_path.name,
            "fairset_report": report_path.name,
        },
        "report": result.report,
    }


_web_assets_dir = _WEB_DIST / "assets"
if _web_assets_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=_web_assets_dir), name="web_assets")
    logger.info("Web UI static assets mounted from %s", _web_assets_dir)
