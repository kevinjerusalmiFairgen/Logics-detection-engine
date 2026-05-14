import pandas as pd

from logic_platform.fairset.prior_parser import (
    parse_prior_dataframe,
    validate_referenced_columns,
)


def make_prior_dataframe():
    return pd.DataFrame(
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
                "Target": "RC_OUT",
                "Source": "SRC_COL",
                "Constraint": "Recoding",
                "B/F Relationship": "Single to Single",
                "Comment": "Single-source recode",
                "Is Implemented": "Yes",
                "Custom Query": "",
                "ID": 99,
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


def test_parse_prior_dataframe_is_headless_and_matches_core_legacy_shape():
    result = parse_prior_dataframe(make_prior_dataframe())

    assert result.warnings == []
    assert result.constraints["BF_SS"] == [
        ["Q1", "Q2", "Q2 depends on Q1", "block_force", True]
    ]
    assert result.constraints["recodings"] == [
        [["Q3r1", "Q3r2"], "SEGMENT", "MS", "Derive segment", True],
        ["SRC_COL", "RC_OUT", "SS", "Single-source recode", True],
    ]
    assert result.structure["recodings"] == [
        {
            "id": "1",
            "name": "1",
            "recode": "SEGMENT",
            "codes": ["Q3r1", "Q3r2"],
        },
        {
            "id": "2",
            "name": "2",
            "recode": "RC_OUT",
            "codes": ["SRC_COL"],
        },
    ]
    assert result.structure["multiSelect"] == [
        {"id": "3", "name": "3", "columns": ["Q4r1", "Q4r2", "Q4r99"]}
    ]


def test_validate_referenced_columns_ignores_blank_cells_and_normalizes_case():
    prior = pd.DataFrame(
        {
            "Target": ["['Q1r1', 'Q1r2']", "Q2"],
            "Source": ["", "Q3"],
        }
    )

    missing = validate_referenced_columns(prior, ["q1r1", "Q1r2", "Q2", "Q3"])

    assert missing == []


def test_parse_prior_dataframe_returns_warnings_instead_of_ui_side_effects():
    prior = make_prior_dataframe()
    prior.loc[0, "B/F Relationship"] = ""

    result = parse_prior_dataframe(prior)

    assert result.constraints["BF_SS"] == []
    assert len(result.warnings) == 1
    assert result.warnings[0].row_id == "1"
    assert result.warnings[0].message == "Missing relationship for Block/Force"
