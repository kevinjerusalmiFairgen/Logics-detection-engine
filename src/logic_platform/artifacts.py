"""Run-scoped artifact storage for local platform jobs."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CANONICAL_ARTIFACTS = {
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
    "fairset_report": "fairset_report.json",
    "fairset_report_xlsx": "fairset_report.xlsx",
}

_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")

STRUCTURE_JSON_ARTIFACT_KEYS = frozenset({"structure_json", "fairset_structure"})
RECODING_SCRUB_ARTIFACT_KEYS = frozenset(
    {
        "structure_json",
        "fairset_structure",
        "fairset_constraints",
        "fairset_report",
    }
)


def sanitize_recoding_artifact(artifact_key: str, payload: Any) -> Any:
    """Normalize legacy scalar ``codes`` / ``recode`` shapes for persisted or served JSON."""
    if artifact_key not in RECODING_SCRUB_ARTIFACT_KEYS:
        return payload
    if artifact_key in STRUCTURE_JSON_ARTIFACT_KEYS and isinstance(payload, dict):
        from logic_platform.fairset.structure import coerce_structure_recodings

        return coerce_structure_recodings(payload)
    from logic_platform.fairset.structure import coerce_recodings_deep

    return coerce_recodings_deep(payload)


def create_run_id(prefix: str = "run") -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{timestamp}_{uuid.uuid4().hex[:8]}"


def _validate_run_id(run_id: str) -> str:
    if not run_id or not _RUN_ID_PATTERN.match(run_id):
        raise ValueError(f"Invalid run id: {run_id!r}")
    return run_id


@dataclass(frozen=True)
class RunArtifacts:
    root: Path
    run_id: str

    @classmethod
    def create(cls, root: str | Path = "runs", run_id: str | None = None) -> "RunArtifacts":
        return cls(root=Path(root), run_id=_validate_run_id(run_id or create_run_id()))

    @property
    def run_dir(self) -> Path:
        return self.root / self.run_id

    def ensure(self) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        return self.run_dir

    def path(self, artifact_key: str) -> Path:
        try:
            filename = CANONICAL_ARTIFACTS[artifact_key]
        except KeyError as exc:
            raise KeyError(f"Unknown artifact key: {artifact_key}") from exc
        return self.run_dir / filename

    def write_json(self, artifact_key: str, payload: Any, *, indent: int = 2) -> Path:
        self.ensure()
        path = self.path(artifact_key)
        out_payload = sanitize_recoding_artifact(artifact_key, payload)
        with path.open("w", encoding="utf-8") as f:
            json.dump(out_payload, f, indent=indent, ensure_ascii=False)
        return path

    def append_event(self, event: dict[str, Any]) -> Path:
        self.ensure()
        path = self.path("events_log")
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return path

    def write_text(self, artifact_key: str, content: str) -> Path:
        self.ensure()
        path = self.path(artifact_key)
        with path.open("w", encoding="utf-8") as f:
            f.write(content)
        return path

    def list_existing(self) -> dict[str, Path]:
        if not self.run_dir.is_dir():
            return {}
        out: dict[str, Path] = {}
        for key in CANONICAL_ARTIFACTS:
            candidate = self.path(key)
            if candidate.is_file():
                out[key] = candidate
        return out
