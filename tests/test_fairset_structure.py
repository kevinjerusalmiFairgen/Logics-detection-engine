import pandas as pd

from logic_platform.fairset.structure import normalize_structure


def test_normalize_structure_enriches_multiselect_and_filters_helper_columns():
    prior_df = pd.DataFrame(
        [
            {
                "Target": "['S3r1', 'S3r98oe', 'S3r1', 'Q2_Rank1']",
                "Source": "",
                "Constraint": "MultiSelect",
                "B/F Relationship": "Single to Multi",
                "Comment": "S3: Sports followed",
                "Is Implemented": "Yes",
                "Custom Query": "",
                "ID": 1,
            }
        ]
    )
    questionnaire = {
        "questions": [
            {
                "id": "S3",
                "text": "Sports followed",
                "type": "multi_select",
                "vars": ["S3r1", "S3r98oe", "S3r1", "Q2_Rank1"],
                "answers": {"S3r1": "Basketball", "S3r98oe": "Other"},
            }
        ]
    }

    structure = normalize_structure(
        {"recodings": [], "multiSelect": [], "typeOfNan": []},
        prior_df=prior_df,
        questionnaire=questionnaire,
    )

    assert structure["multiSelect"] == [
        {
            "id": "S3",
            "name": "Sports followed",
            "columns": ["S3r1"],
            "dataType": "LITERAL",
            "contentType": "BINARY_MULTISELECT",
            "shortColumnLabel": [{"name": "S3r1", "label": "Basketball"}],
        }
    ]
    assert "codes" not in structure["multiSelect"][0]


def test_normalize_structure_accepts_none_structure():
    structure = normalize_structure(None)
    assert structure["recodings"] == []
    assert structure["multiSelect"] == []
    assert structure["typeOfNan"] == []


def test_normalize_structure_questionnaire_questions_none_is_safe():
    structure = normalize_structure(
        {"recodings": [], "multiSelect": [], "typeOfNan": []},
        questionnaire={"questions": None},
    )
    assert structure["multiSelect"] == []


def test_normalize_structure_recoding_codes_array_recode_scalar_or_list():
    structure = normalize_structure(
        {
            "recodings": [
                {
                    "id": "0",
                    "name": "0",
                    "recode": "SEGMENT_A",
                    "codes": "VAR1",
                },
                {
                    "id": "1",
                    "name": "1",
                    "recode": ["SEGMENT_B", " EXTRA "],
                    "codes": ["VAR2", " VAR3 "],
                },
            ],
            "multiSelect": [],
            "typeOfNan": [],
        }
    )

    assert structure["recodings"][0]["codes"] == ["VAR1"]
    assert structure["recodings"][0]["recode"] == "SEGMENT_A"
    assert structure["recodings"][1]["codes"] == ["VAR2", "VAR3"]
    assert structure["recodings"][1]["recode"] == ["SEGMENT_B", "EXTRA"]


def test_coerce_recodings_deep_nested_recodings_key():
    from logic_platform.fairset.structure import coerce_recodings_deep

    payload = {
        "BF_SS": [["a", "b", "c", "block_force", True]],
        "recodings": [["S2_Final", "S2a_Final", "SS", "", True]],
        "extra": {
            "recodings": [
                {"id": "0", "name": "0", "recode": "S2a_Final", "codes": "S2_Final"},
            ]
        },
    }
    out = coerce_recodings_deep(payload)
    assert out["recodings"][0] == ["S2_Final", "S2a_Final", "SS", "", True]
    assert out["extra"]["recodings"][0]["codes"] == ["S2_Final"]
    assert out["extra"]["recodings"][0]["recode"] == "S2a_Final"


def test_coerce_structure_recodings_standalone():
    from logic_platform.fairset.structure import coerce_structure_recodings

    out = coerce_structure_recodings(
        {
            "recodings": [
                {"id": "0", "recode": "T1", "codes": "SRC"},
                {"id": "1", "recode": ["A", "B"], "codes": ["x", "y"]},
            ],
            "multiSelect": [],
            "typeOfNan": [],
        }
    )
    assert out["recodings"][0]["recode"] == "T1"
    assert out["recodings"][0]["codes"] == ["SRC"]
    assert out["recodings"][1]["recode"] == ["A", "B"]
