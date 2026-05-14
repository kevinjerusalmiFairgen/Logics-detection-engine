#!/usr/bin/env python3
"""
Step 6: Final JSON Assembly

Combines derived variables and questions into the final JSON structure.
Ensures schema compliance and proper formatting.

Usage:
    python s6_assemble.py --derived s4_result.json --questions s5_result.json --output s6_result.json
"""

import json
import os
import argparse
from typing import Dict, List, Set

from logic_platform.utils import flatten_vars


def _is_materializable_recode(dv: Dict) -> bool:
    """True when derived var is a non-trivial transformation (not var→itself metadata)."""
    var = (dv.get("var") or "").strip()
    if not var:
        return False
    raw_src = dv.get("source_vars") or []
    sources = [str(s).strip() for s in raw_src if str(s).strip()]
    if not sources:
        return False
    if len(sources) == 1 and sources[0] == var:
        return False
    return True


def _existing_recode_targets(questions: List[Dict]) -> Set[str]:
    out: Set[str] = set()
    for q in questions:
        for log in q.get("logics") or []:
            if log.get("type") != "recode":
                continue
            for t in log.get("target_vars") or []:
                if t:
                    out.add(str(t))
    return out


def _question_var_set(q: Dict) -> Set[str]:
    return set(flatten_vars(q.get("vars", [])))


def _pick_question_index_for_recode(questions: List[Dict], source_vars: List[str]) -> int:
    """Attach recode logic to the first question (in order) that owns any source var; else last."""
    if not questions:
        return -1
    for i, q in enumerate(questions):
        qv = _question_var_set(q)
        if any(s in qv for s in source_vars):
            return i
    return len(questions) - 1


def materialize_recode_logics(
    questions: List[Dict], derived_variables: List[Dict]
) -> int:
    """
    Append type=recode logic entries from derived_variables (idempotent).

    Skips trivial self-only rows. Skips targets already present as recode logics.
    Each new logic is placed on the first question that maps any source_vars.
    """
    if not questions or not derived_variables:
        return 0
    existing_targets = _existing_recode_targets(questions)
    added = 0
    for dv in derived_variables:
        if not _is_materializable_recode(dv):
            continue
        var = (dv.get("var") or "").strip()
        if var in existing_targets:
            continue
        sources = [str(s).strip() for s in (dv.get("source_vars") or []) if str(s).strip()]
        if not sources:
            continue
        desc = (dv.get("description") or "").strip()
        condition = desc if desc else f"Recode: {';'.join(sources)} -> {var}"
        idx = _pick_question_index_for_recode(questions, sources)
        if idx < 0:
            continue
        logic_entry = {
            "type": "recode",
            "condition": condition[:2000],
            "source_vars": list(sources),
            "target_vars": [var],
        }
        q = questions[idx]
        if "logics" not in q:
            q["logics"] = []
        q["logics"].append(logic_entry)
        existing_targets.add(var)
        added += 1
    return added


def _flatten_single_var_grids(questions: List[Dict]) -> int:
    """Convert grid questions where every row has exactly one variable to multi_select.

    Returns the number of questions converted.
    """
    converted = 0
    for q in questions:
        if q.get("type") != "grid":
            continue
        vars_ = q.get("vars", [])
        if not vars_ or not isinstance(vars_[0], list):
            continue
        if all(isinstance(row, list) and len(row) == 1 for row in vars_):
            q["vars"] = [row[0] for row in vars_]
            q["type"] = "multi_select"
            converted += 1
    return converted


def assemble_final_json(
    derived_variables: List[Dict],
    questions_with_logic: List[Dict]
) -> Dict:
    """
    Combine derived variables and questions into final JSON.
    
    Returns:
        Final JSON structure: {"derived_variables": [...], "questions": [...]}
    """
    # Ensure answers is {} for all questions
    for question in questions_with_logic:
        question["answers"] = {}
        if "logics" not in question:
            question["logics"] = []

    n_flat = _flatten_single_var_grids(questions_with_logic)
    if n_flat:
        print(f"  Converted {n_flat} single-dimension grid(s) to multi_select.")
    
    # Ensure derived_variables have required fields
    for dv in derived_variables:
        if "source_vars" not in dv or not dv["source_vars"]:
            dv["source_vars"] = [dv["var"]]
        if "description" not in dv:
            dv["description"] = ""

    materialize_recode_logics(questions_with_logic, derived_variables)

    return {
        "derived_variables": derived_variables,
        "questions": questions_with_logic
    }


def clean_json_for_output(final_json: Dict) -> Dict:
    """
    Clean the final JSON for schema compliance.
    
    Removes extra keys not in the schema.
    """
    allowed_top_keys = {"derived_variables", "questions"}
    allowed_q_keys = {"id", "section", "text", "type", "vars", "answers", "logics"}
    allowed_logic_keys = {"type", "condition", "source_vars", "target_vars"}
    allowed_dv_keys = {"var", "source_vars", "description"}
    
    cleaned = {"derived_variables": [], "questions": []}
    
    # Clean derived variables
    for dv in final_json.get("derived_variables", []):
        cleaned_dv = {k: v for k, v in dv.items() if k in allowed_dv_keys}
        if "var" in cleaned_dv:
            if "source_vars" not in cleaned_dv or not cleaned_dv["source_vars"]:
                cleaned_dv["source_vars"] = [cleaned_dv["var"]]
            if "description" not in cleaned_dv:
                cleaned_dv["description"] = ""
            cleaned["derived_variables"].append(cleaned_dv)
    
    # Clean questions
    for q in final_json.get("questions", []):
        cleaned_q = {k: v for k, v in q.items() if k in allowed_q_keys}
        cleaned_q["answers"] = {}
        
        if "logics" not in cleaned_q:
            cleaned_q["logics"] = []
        else:
            cleaned_logics = []
            for logic in cleaned_q["logics"]:
                cleaned_logic = {k: v for k, v in logic.items() if k in allowed_logic_keys}
                if all(k in cleaned_logic for k in allowed_logic_keys):
                    cleaned_logics.append(cleaned_logic)
            cleaned_q["logics"] = cleaned_logics
        
        cleaned["questions"].append(cleaned_q)
    
    return cleaned


def main():
    parser = argparse.ArgumentParser(description="Step 6: Assemble final JSON")
    parser.add_argument("--derived", "-d", required=True, help="Path to resolution JSON (from Step 4)")
    parser.add_argument("--questions", "-q", required=True, help="Path to logic JSON (from Step 5)")
    parser.add_argument("--output", "-o", default="output/s6_assembled.json", help="Output JSON file")
    parser.add_argument("--clean", "-c", action="store_true", help="Clean extra fields")
    args = parser.parse_args()
    
    print("\n[Step 6] Final JSON Assembly")
    print("=" * 50)
    
    with open(args.derived) as f:
        derived_data = json.load(f)
    derived = derived_data.get("derived_variables", [])
    
    with open(args.questions) as f:
        q_data = json.load(f)
    questions = q_data if isinstance(q_data, list) else q_data.get("questions", [])
    
    result = assemble_final_json(derived, questions)
    
    if args.clean:
        result = clean_json_for_output(result)
    
    print(f"  Derived variables: {len(result['derived_variables'])}")
    print(f"  Questions: {len(result['questions'])}")
    
    total_logics = sum(len(q.get("logics", [])) for q in result["questions"])
    print(f"  Total logic rules: {total_logics}")
    
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)
    
    print(f"\nResult saved to: {args.output}")


if __name__ == "__main__":
    main()
