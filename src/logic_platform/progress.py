"""Progress estimation for run-scoped pipeline executions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from logic_platform.artifacts import RunArtifacts


STEP_WEIGHTS = {
    1: 12,
    2: 18,
    3: 34,
    4: 48,
    5: 62,
    6: 78,
    7: 90,
    8: 96,
}

STEP_LABELS = {
    1: "PDF extraction",
    2: "Dataset metadata extraction",
    3: "Question-to-variable mapping",
    4: "Unmapped variable resolution",
    5: "Pattern discovery",
    6: "Logic extraction",
    7: "Final assembly",
    8: "Validation",
}


def build_run_progress(artifacts: RunArtifacts) -> dict[str, Any]:
    run_dir = artifacts.run_dir
    events_path = artifacts.path("events_log")
    log_path = artifacts.path("run_log")
    validation_path = artifacts.path("validation_report")
    events = _read_events(events_path)
    log_text = _read_tail(log_path, max_chars=16000)
    current_step = _current_step(log_text)
    failed_event = next((event for event in reversed(events) if event.get("event") == "pipeline_failed"), None)
    has_failure = failed_event or _status_file_failed(validation_path)
    has_newer_log_activity = _has_newer_log_activity(log_path, [events_path, validation_path])

    if artifacts.path("logics_json").is_file():
        status = "complete"
        percent = 100
        label = "Logics JSON ready"
    elif has_failure and not has_newer_log_activity:
        status = "failed"
        percent = min(_percent_for_step(current_step), 99)
        label = failed_event.get("message", "Pipeline failed") if failed_event else "Pipeline failed"
    elif any(event.get("event") == "pipeline_started" for event in events) or has_newer_log_activity:
        status = "running"
        percent = _percent_for_step(current_step)
        label = STEP_LABELS.get(current_step, "Running pipeline")
    elif run_dir.is_dir():
        status = "created"
        percent = 5
        label = "Run created"
    else:
        status = "missing"
        percent = 0
        label = "Run not found"

    return {
        "run_id": artifacts.run_id,
        "status": status,
        "percent": percent,
        "current_step": current_step,
        "current_step_label": STEP_LABELS.get(current_step),
        "message": label,
        "events": events[-20:],
        "log_tail": log_text[-4000:],
    }


def _current_step(log_text: str) -> int | None:
    matches = re.findall(r"\[Step\s+(\d+)\]", log_text)
    return int(matches[-1]) if matches else None


def _percent_for_step(step: int | None) -> int:
    if step is None:
        return 10
    return STEP_WEIGHTS.get(step, 10)


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _read_tail(path: Path, max_chars: int) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-max_chars:]


def _status_file_failed(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return data.get("status") == "failed"


def _has_newer_log_activity(log_path: Path, marker_paths: list[Path]) -> bool:
    if not log_path.is_file():
        return False
    existing_markers = [path for path in marker_paths if path.is_file()]
    if not existing_markers:
        return False
    newest_marker_time = max(path.stat().st_mtime for path in existing_markers)
    return log_path.stat().st_mtime > newest_marker_time + 1
