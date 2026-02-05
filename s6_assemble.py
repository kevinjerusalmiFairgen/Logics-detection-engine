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
from typing import Dict, List

from utils import flatten_vars


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
    
    # Ensure derived_variables have required fields
    for dv in derived_variables:
        if "source_vars" not in dv or not dv["source_vars"]:
            dv["source_vars"] = [dv["var"]]
        if "description" not in dv:
            dv["description"] = ""
    
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
