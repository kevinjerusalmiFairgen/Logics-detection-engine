from logic_platform.digitization.logics_export import export_logics_json_from_questionnaire


def test_export_logics_json_from_questionnaire_outputs_rows_without_csv_artifact():
    questionnaire = {
        "derived_variables": [],
        "questions": [
            {
                "id": "Q1",
                "section": "S",
                "text": "Choose options",
                "type": "multi_select",
                "vars": ["Q1r1", "Q1r2"],
                "answers": {},
                "logics": [],
            },
            {
                "id": "Q2",
                "section": "S",
                "text": "Shown if Q1r1",
                "type": "single_select",
                "vars": ["Q2"],
                "answers": {},
                "logics": [
                    {
                        "type": "skip",
                        "condition": "Q1r1 != 1",
                        "source_vars": ["Q1r1"],
                        "target_vars": ["Q2"],
                    }
                ],
            },
        ],
    }

    result = export_logics_json_from_questionnaire(questionnaire)

    assert result.payload["schema"] == "logic_platform.logics.v1"
    assert result.payload["columns"] == [
        "Target",
        "Source",
        "Constraint",
        "B/F Relationship",
        "Comment",
        "Is Implemented",
        "Custom Query",
        "ID",
    ]
    assert result.payload["row_count"] == 2
    assert result.payload["rows"][0]["Target"] == "Q2"
    assert result.payload["rows"][0]["Constraint"] == "Block"
    assert result.payload["rows"][1]["Target"] == "['Q1r1', 'Q1r2']"
    assert result.payload["rows"][1]["Constraint"] == "MultiSelect"
