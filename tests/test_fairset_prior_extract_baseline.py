"""Regression tests for ``prior_extract.priorFileExtract`` / ``check_columns_presence``."""

from __future__ import annotations

import pandas as pd

from logic_platform.fairset import prior_extract


def test_prior_file_extract_maps_core_rows_to_constraints_and_structure():
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

    constraints_json, structure_json = prior_extract.priorFileExtract(prior)

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
    prior = pd.DataFrame(
        {
            "Target": ["['Q1r1', 'Q1r2']", "Q2"],
            "Source": ["", "Q3"],
        }
    )
    dataset = pd.DataFrame(columns=["q1r1", "Q1r2", "Q2", "Q3"])

    # Legacy FairsetReview behavior reports a blank Source cell as missing column ``""``.
    assert prior_extract.check_columns_presence(prior, dataset, ["Target", "Source"]) == [""]
