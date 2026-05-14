from logic_platform.logics.extract_logic_table import (
    MULTISELECT_LOGIC_TYPE,
    _internal_to_export_rows,
    extract_multiselect_group_rows,
)


def test_multiselect_rows_include_all_json_questions_when_pattern_report_is_partial():
    questionnaire = {
        "questions": [
            {
                "id": "Q1",
                "type": "multi_select",
                "text": "First multi select",
                "vars": ["Q1r1", "Q1r2"],
            },
            {
                "id": "Q2",
                "type": "single_select",
                "text": "Not a multi select",
                "vars": ["Q2"],
            },
            {
                "id": "Q3",
                "type": "multi_select",
                "text": "Second multi select",
                "vars": ["Q3r1", "Q3r2", "Q3r99"],
            },
        ]
    }
    pattern_report = {
        "multiselect_groups": [
            {
                "question_id": "Q1",
                "vars": ["SHOULD_NOT_REPLACE_JSON_VARS"],
                "exclusive_vars": ["Q1r99"],
                "structure_note": "Enriched pattern note",
            }
        ]
    }

    rows = extract_multiselect_group_rows(questionnaire, pattern_report)

    assert len(rows) == 2
    assert [row["logic_type"] for row in rows] == [
        MULTISELECT_LOGIC_TYPE,
        MULTISELECT_LOGIC_TYPE,
    ]
    assert rows[0]["target"] == "Q1r1;Q1r2"
    assert rows[0]["description"] == "Q1: Enriched pattern note"
    assert rows[1]["target"] == "Q3r1;Q3r2;Q3r99"
    assert rows[1]["description"] == "Q3: Second multi select"


def test_pattern_only_multiselect_groups_are_preserved_for_non_question_groups():
    questionnaire = {"questions": []}
    pattern_report = {
        "multiselect_groups": [
            {
                "question_id": "DERIVED_GROUP",
                "vars": ["D1", "D2"],
                "exclusive_vars": ["D99"],
                "structure_note": "Derived-only group",
            }
        ]
    }

    rows = extract_multiselect_group_rows(questionnaire, pattern_report)

    assert rows == [
        {
            "source": "",
            "target": "D1;D2;D99",
            "description": "DERIVED_GROUP: Derived-only group",
            "logic_type": MULTISELECT_LOGIC_TYPE,
        }
    ]


def test_multiselect_rows_export_as_multiselect_constraint():
    rows = extract_multiselect_group_rows(
        {
            "questions": [
                {
                    "id": "Q1",
                    "type": "multi_select",
                    "text": "Select all",
                    "vars": ["Q1r1", "Q1r2"],
                }
            ]
        }
    )

    export_rows = _internal_to_export_rows(rows)

    assert export_rows[0]["Constraint"] == "MultiSelect"
    assert export_rows[0]["B/F Relationship"] == "Single to Multi"
    assert export_rows[0]["Target"] == "['Q1r1', 'Q1r2']"
