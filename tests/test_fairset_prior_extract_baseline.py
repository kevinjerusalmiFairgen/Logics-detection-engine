import importlib.util
import sys
import types
from pathlib import Path

import pandas as pd
import pytest


FAIRSET_PRIOR_EXTRACT = Path(
    "/Users/kevinjerusalmi/Programming/FairsetReview/scripts/priorFile_extract.py"
)


def load_prior_extract_module():
    if not FAIRSET_PRIOR_EXTRACT.is_file():
        pytest.skip("FairsetReview priorFile_extract.py is not available on this machine")

    streamlit_stub = types.SimpleNamespace(
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        stop=lambda *args, **kwargs: None,
    )
    sys.modules.setdefault("streamlit", streamlit_stub)

    spec = importlib.util.spec_from_file_location(
        "fairset_prior_extract_baseline", FAIRSET_PRIOR_EXTRACT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_prior_file_extract_maps_core_rows_to_constraints_and_structure():
    module = load_prior_extract_module()
    prior = pd.DataFrame(
        [
            {
                "Target": "Q2",
                "Source": "Q1",
                "Constraint": "Block/Force",
                "B/F Relationship": "Single to Single",
                "Comment": "Q2 depends on Q1",
                "Is Implemented": "Yes",
                "Custom Query": "",
                "ID": 1,
            },
            {
                "Target": "SEGMENT",
                "Source": "['Q3r1', 'Q3r2']",
                "Constraint": "Recoding",
                "B/F Relationship": "Multi to Single",
                "Comment": "Derive segment",
                "Is Implemented": "Yes",
                "Custom Query": "",
                "ID": 2,
            },
            {
                "Target": "['Q4r1', 'Q4r2', 'Q4r99']",
                "Source": "",
                "Constraint": "MultiSelect",
                "B/F Relationship": "Single to Multi",
                "Comment": "Q4 group",
                "Is Implemented": "Yes",
                "Custom Query": "",
                "ID": 3,
            },
        ]
    )

    constraints_json, structure_json = module.priorFileExtract(prior)

    assert constraints_json["BF_SS"] == [
        ["Q1", "Q2", "Q2 depends on Q1", "block_force", True]
    ]
    assert constraints_json["recodings"] == [
        [["Q3r1", "Q3r2"], "SEGMENT", "MS", "Derive segment", True]
    ]
    assert structure_json["recodings"] == [
        {
            "id": "1",
            "name": "1",
            "recode": "SEGMENT",
            "codes": ["Q3r1", "Q3r2"],
        }
    ]
    assert structure_json["multiSelect"] == [
        {"id": "2", "name": "2", "columns": ["Q4r1", "Q4r2", "Q4r99"]}
    ]


def test_check_columns_presence_handles_stringified_lists_and_existing_empty_source_behavior():
    module = load_prior_extract_module()
    prior = pd.DataFrame(
        {
            "Target": ["['Q1r1', 'Q1r2']", "Q2"],
            "Source": ["", "Q3"],
        }
    )
    dataset = pd.DataFrame(columns=["q1r1", "Q1r2", "Q2", "Q3"])

    # Existing FairsetReview behavior reports a blank Source cell as [""].
    # The Streamlit app special-cases this value; the refactor should make it
    # an explicit parser warning instead of a column error.
    assert module.check_columns_presence(prior, dataset, ["Target", "Source"]) == [""]
