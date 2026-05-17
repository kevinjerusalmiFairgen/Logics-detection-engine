"""JSON-safe façade over legacy FairsetReview prior parsing and constraint checks."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd

from logic_platform.fairset import prior_extract

_CHECKS: ModuleType | None = None


class _Placeholder:
    def progress(self, *_a, **_k) -> None:
        return None

    def text(self, *_a, **_k) -> None:
        return None

    def success(self, *_a, **_k) -> None:
        return None


class _StreamlitStub(ModuleType):
    """Minimal stand-in so ``constraint_checks`` (written for Streamlit) runs headless."""

    def __init__(self) -> None:
        super().__init__("streamlit")

    def empty(self) -> _Placeholder:
        return _Placeholder()

    def warning(self, *_a, **_k) -> None:
        return None

    def error(self, *_a, **_k) -> None:
        return None

    def write(self, *_a, **_k) -> None:
        return None

    def text(self, *_a, **_k) -> None:
        return None

    def dataframe(self, *_a, **_k) -> None:
        return None


def _install_streamlit_stub() -> None:
    sys.modules["streamlit"] = _StreamlitStub()


def _constraint_checks() -> ModuleType:
    global _CHECKS
    if _CHECKS is None:
        _install_streamlit_stub()
        from logic_platform.fairset import constraint_checks as mod

        _CHECKS = mod
    return _CHECKS


def prior_file_extract(prior_df: pd.DataFrame) -> tuple[dict[str, list], dict[str, list]]:
    constraints, structure = prior_extract.priorFileExtract(prior_df.copy())
    c, s = _to_jsonable(constraints), _to_jsonable(structure)
    return (c if isinstance(c, dict) else {}), (s if isinstance(s, dict) else {})


def check_columns_presence(prior_df: pd.DataFrame, data_df: pd.DataFrame, cols: list[str]) -> list[str]:
    return prior_extract.check_columns_presence(prior_df.copy(), data_df.copy(), cols)


def run_logic_analysis(
    constraints: dict[str, list],
    train_df: pd.DataFrame,
    fairset_df: pd.DataFrame,
    *,
    empty_values: list[Any] | None = None,
) -> list[dict[str, Any]]:
    checks = _constraint_checks()
    logic = checks.LogicFunctions(
        "Dataset",
        train_df.copy(),
        fairset_df.copy(),
        empty_values=empty_values or [],
    )
    out = _to_jsonable(logic.run_analysis(constraints))
    return out if isinstance(out, list) else []


def _to_jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, tuple | set):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return None if pd.isna(obj) else float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.ndarray, pd.Series, pd.Index)):
        return _to_jsonable(obj.tolist())
    if isinstance(obj, pd.DataFrame):
        return _to_jsonable(obj.to_dict(orient="records"))
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    try:
        if pd.isna(obj):
            return None
    except Exception:
        pass
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)
