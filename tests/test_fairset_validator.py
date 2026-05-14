import pandas as pd

from logic_platform.fairset.validator import run_review_from_dataframes


def test_review_from_dataframes_detects_block_single_to_single_violation():
    prior = pd.DataFrame(
        [
            {
                "Target": "Q2",
                "Source": "Q1",
                "Constraint": "Block",
                "B/F Relationship": "Single to Single",
                "Comment": "Block Q2 when Q1 is 1",
                "Is Implemented": "Yes",
                "Custom Query": "",
                "ID": 1,
            }
        ]
    )
    train = pd.DataFrame({"Q1": [1, 1, 2], "Q2": [None, None, "shown"]})
    fairset = pd.DataFrame({"Q1": [1, 2], "Q2": ["should be blank", "shown"]})

    result = run_review_from_dataframes(prior, train, fairset)

    assert result.missing_columns == []
    assert result.warnings == []
    assert len(result.report) == 1
    assert result.report[0]["Type"] == "Block Single-to-Single"
    assert result.report[0]["is_valid"] is False
    assert result.report[0]["Rows"] == [0]
    assert result.report[0]["Dataframe"] == [{"Q1": "1.0", "Q2": "should be blank"}]


def test_review_from_dataframes_reports_missing_columns_before_evaluation():
    prior = pd.DataFrame(
        [
            {
                "Target": "MISSING",
                "Source": "Q1",
                "Constraint": "Block",
                "B/F Relationship": "Single to Single",
                "Comment": "Bad target",
                "Is Implemented": "Yes",
                "Custom Query": "",
                "ID": 1,
            }
        ]
    )
    train = pd.DataFrame({"Q1": [1]})
    fairset = pd.DataFrame({"Q1": [1]})

    result = run_review_from_dataframes(prior, train, fairset)

    assert result.missing_columns == ["missing"]
    assert result.report == []


def test_review_from_dataframes_uses_streamlit_uniqueness_check():
    prior = pd.DataFrame(
        [
            {
                "Target": "['Q1r1', 'Q1r2']",
                "Source": "",
                "Constraint": "Uniqueness",
                "B/F Relationship": "",
                "Comment": "Unique ranking",
                "Is Implemented": "Yes",
                "Custom Query": "",
                "ID": 1,
            }
        ]
    )
    train = pd.DataFrame({"Q1r1": [1], "Q1r2": [2]})
    fairset = pd.DataFrame({"Q1r1": [1], "Q1r2": [1]})

    result = run_review_from_dataframes(prior, train, fairset)

    assert len(result.report) == 1
    assert result.report[0]["Type"] == "Uniqueness"
    assert result.report[0]["Description"] == "Uniqueness - (['Q1r1', 'Q1r2'])"
    assert result.report[0]["is_valid"] is False
    assert result.report[0]["Rows"] == [0, 0]
