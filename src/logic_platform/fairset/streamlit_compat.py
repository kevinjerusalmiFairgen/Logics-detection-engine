"""Compatibility layer around the original Streamlit Fairset Review functions."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd


FAIRSET_REVIEW_ROOT = Path(
    "/Users/kevinjerusalmi/Programming/FairsetReview"
)


class _StreamlitPlaceholder:
    def progress(self, *_args, **_kwargs) -> None:
        return None

    def text(self, *_args, **_kwargs) -> None:
        return None

    def success(self, *_args, **_kwargs) -> None:
        return None


class _StreamlitShim(ModuleType):
    def __init__(self) -> None:
        super().__init__("streamlit")

    def empty(self) -> _StreamlitPlaceholder:
        return _StreamlitPlaceholder()

    def warning(self, *_args, **_kwargs) -> None:
        return None

    def error(self, *_args, **_kwargs) -> None:
        return None

    def write(self, *_args, **_kwargs) -> None:
        return None

    def text(self, *_args, **_kwargs) -> None:
        return None

    def dataframe(self, *_args, **_kwargs) -> None:
        return None


def prior_file_extract(prior_df: pd.DataFrame) -> tuple[dict[str, list], dict[str, list]]:
    """Run the original Streamlit priorFileExtract function."""
    module = _load_legacy_module("priorFile_extract")
    constraints, structure = module.priorFileExtract(prior_df.copy())
    return _to_jsonable(constraints), _to_jsonable(structure)


def check_columns_presence(prior_df: pd.DataFrame, data_df: pd.DataFrame, cols: list[str]) -> list[str]:
    """Run the original Streamlit check_columns_presence function."""
    module = _load_legacy_module("priorFile_extract")
    return module.check_columns_presence(prior_df.copy(), data_df.copy(), cols)


def run_logic_analysis(
    constraints: dict[str, list],
    train_df: pd.DataFrame,
    fairset_df: pd.DataFrame,
    *,
    empty_values: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Run the original Streamlit LogicFunctions.run_analysis function."""
    module = _load_legacy_module("fairset_check")
    logic_instance = module.LogicFunctions(
        "Dataset",
        train_df.copy(),
        fairset_df.copy(),
        empty_values=empty_values or [],
    )
    return _to_jsonable(logic_instance.run_analysis(constraints))


def _load_legacy_module(name: str):
    if not FAIRSET_REVIEW_ROOT.is_dir():
        raise RuntimeError(f"FairsetReview folder not found: {FAIRSET_REVIEW_ROOT}")

    _install_streamlit_shim()
    module_name = f"_legacy_fairset_review_{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]

    module_path = FAIRSET_REVIEW_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load FairsetReview module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _install_streamlit_shim() -> None:
    if "streamlit" not in sys.modules:
        sys.modules["streamlit"] = _StreamlitShim()


def _to_jsonable(obj):
    if isinstance(obj, dict):
        return {str(key): _to_jsonable(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_to_jsonable(item) for item in obj]
    if isinstance(obj, tuple | set):
        return [_to_jsonable(item) for item in obj]
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
    json.dumps(obj)
    return obj
