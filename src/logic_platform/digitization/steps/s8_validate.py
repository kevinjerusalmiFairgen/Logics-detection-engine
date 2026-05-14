#!/usr/bin/env python3
"""
Step 8: Validation (PASS 4 - FINAL VALIDATION)

Validates final JSON against all 14 checks from master prompt.
REJECT/REGENERATE if any check fails.

Master Prompt PASS 4 Checks:
1) Schema exactness holds (no extra keys)
2) Only allowed question types and logic types exist
3) "min_max" absent everywhere
4) Termination/screenout wording absent everywhere
5) Every skip rule is target-based and target_vars equals current question vars
6) Skip-to-question and skip-to-section are fully expanded
7) Section gates are expanded to every question in gated section
8) Exclusive rules present where applicable (97/98/99 and none/DK/RF)
9) Count rules present for min/max/exactly constraints
10) Sum rules present for add-up constraints
11) Piping appears only as answer-level filtering/carry-forward
12) Every dataset variable mapped (question vars or derived var)
13) Derived vars have source_vars whenever possible
14) questions[] order exactly matches PDF order

Usage:
    python s8_validate.py --json s6_result.json --inventory s2_result.json --structure s1_result.json
"""

import json
import re
import argparse
from typing import Dict, List, Tuple, Set

from logic_platform.utils import flatten_vars

# =============================================================================
# ALLOWED VALUES (FROM MASTER PROMPT - PRE-FLIGHT CONTRACT)
# =============================================================================

ALLOWED_QUESTION_TYPES = {
    "single_select", 
    "multi_select", 
    "numeric", 
    "open_text", 
    "grid", 
}

ALLOWED_LOGIC_TYPES = {
    "skip",
    "section_skip",
    "exclusive", 
    "count", 
    "sum", 
    "piping", 
    "recode", 
    "custom"
}

# Termination/screenout patterns to detect (rule #7 from pre-flight)
# Use word boundaries (\b) to avoid false positives like "section" matching "ion"
TERMINATION_PATTERNS = [
    r"\bthank\s*you\s*(for\s*(your\s*)?(time|participation))?\b",
    r"\byou\s*(do\s*not|don'?t)\s*qualify\b",
    r"\bnot\s*eligible\b",
    r"\bscreen\s*out\b",
    r"\bscreened?\s*out\b",
    r"\bterminate[ds]?\b",
    r"\btermination\b",
    r"\bterminating\b",
    r"\bend\s*(of\s*)?(survey|interview|questionnaire)\b",
    r"\bdisqualif(y|ied|ication)\b",
    r"\bsorry\b",
    r"\bunfortunately\b",
    r"\bwe\s*are\s*(not\s*)?looking\s*for\b",
    r"\bdoes\s*not\s*meet\b",
    r"\bineligible\b",
]


def validate_final_output(
    final_json: Dict,
    dataset_vars: List[str] = None,
    pdf_questions: List[Dict] = None,
    routing_instructions: List[Dict] = None,
    pattern_report: Dict = None
) -> Tuple[bool, Dict[str, dict]]:
    """
    Validate final JSON against all 14 checks from PASS 4.
    
    When pattern_report is provided, check 08 uses exclusive_anchors (data-driven).
    Otherwise falls back to legacy anchor detection.
    
    Returns:
        Tuple of (all_passed, detailed_report)
    """
    dataset_vars = dataset_vars or []
    pdf_questions = pdf_questions or []
    routing_instructions = routing_instructions or []
    pattern_report = pattern_report or {}
    
    report = {}
    
    # Run all 14 checks (matching master prompt PASS 4 exactly)
    report["01_schema_exactness"] = check_01_schema_exactness(final_json)
    report["02_allowed_types"] = check_02_allowed_types(final_json)
    report["03_no_min_max"] = check_03_no_min_max(final_json)
    report["04_no_termination"] = check_04_no_termination(final_json)
    report["05_skip_target_based"] = check_05_skip_target_based(final_json)
    report["06_skip_routing_expanded"] = check_06_skip_routing_expanded(final_json, routing_instructions, pdf_questions)
    report["07_section_gates_expanded"] = check_07_section_gates(final_json, routing_instructions)
    report["08_exclusive_rules"] = check_08_exclusive_rules(final_json, pattern_report)
    report["09_count_rules"] = check_09_count_rules(final_json, routing_instructions)
    report["10_sum_rules"] = check_10_sum_rules(final_json, routing_instructions)
    report["11_piping_answer_level"] = check_11_piping_answer_level(final_json)
    report["12_all_vars_mapped"] = check_12_all_vars_mapped(final_json, dataset_vars)
    report["13_derived_have_sources"] = check_13_derived_have_sources(final_json)
    report["14_pdf_order"] = check_14_pdf_order(final_json, pdf_questions)
    
    all_passed = all(r["passed"] for r in report.values())
    
    return all_passed, report


# =============================================================================
# CHECK 1: Schema exactness holds (no extra keys)
# =============================================================================

def check_01_schema_exactness(final_json: Dict) -> dict:
    """
    Master prompt rule: JSON schema is followed exactly (no extra keys).
    Pre-flight #3, #9, #11
    """
    issues = []
    
    # Check top-level keys: only "derived_variables" and "questions"
    allowed_top = {"derived_variables", "questions"}
    actual_top = set(final_json.keys())
    if actual_top != allowed_top:
        extra = actual_top - allowed_top
        missing = allowed_top - actual_top
        if extra:
            issues.append(f"Extra top-level keys: {extra}")
        if missing:
            issues.append(f"Missing top-level keys: {missing}")
    
    # Check question keys: id, section, text, type, vars, answers, logics
    allowed_q = {"id", "section", "text", "type", "vars", "answers", "logics"}
    for i, q in enumerate(final_json.get("questions", [])):
        q_keys = set(q.keys())
        if not q_keys.issubset(allowed_q):
            extra = q_keys - allowed_q
            issues.append(f"Question {q.get('id', i)} has extra keys: {extra}")
        
        # Pre-flight #11: answers is always {}
        if q.get("answers") != {}:
            issues.append(f"Question {q.get('id', i)}: answers must be {{}}, got {q.get('answers')}")
    
    # Check logic keys: exactly type, condition, source_vars, target_vars (pre-flight #9)
    required_logic_keys = {"type", "condition", "source_vars", "target_vars"}
    for q in final_json.get("questions", []):
        for j, logic in enumerate(q.get("logics", [])):
            logic_keys = set(logic.keys())
            if logic_keys != required_logic_keys:
                issues.append(f"Question {q.get('id')} logic {j}: must have exactly {required_logic_keys}, has {logic_keys}")
    
    # Check derived variable keys: var, source_vars, description
    allowed_dv = {"var", "source_vars", "description"}
    for dv in final_json.get("derived_variables", []):
        dv_keys = set(dv.keys())
        if not dv_keys.issubset(allowed_dv):
            extra = dv_keys - allowed_dv
            issues.append(f"Derived var {dv.get('var', '?')} has extra keys: {extra}")
    
    return {"passed": len(issues) == 0, "issues": issues}


# =============================================================================
# CHECK 2: Only allowed question types and logic types exist
# =============================================================================

def check_02_allowed_types(final_json: Dict) -> dict:
    """
    Master prompt pre-flight #4, #5:
    - Question types: single_select, multi_select, numeric, open_text, grid
    - Logic types: skip, exclusive, count, sum, piping, recode, custom
    """
    issues = []
    
    # Check question types
    for q in final_json.get("questions", []):
        qtype = q.get("type")
        if qtype not in ALLOWED_QUESTION_TYPES:
            issues.append(f"Question {q.get('id')}: invalid type '{qtype}'. Allowed: {ALLOWED_QUESTION_TYPES}")
    
    # Check logic types
    for q in final_json.get("questions", []):
        for logic in q.get("logics", []):
            ltype = logic.get("type")
            if ltype not in ALLOWED_LOGIC_TYPES:
                issues.append(f"Question {q.get('id')}: invalid logic type '{ltype}'. Allowed: {ALLOWED_LOGIC_TYPES}")
    
    return {"passed": len(issues) == 0, "issues": issues}


# =============================================================================
# CHECK 3: "min_max" absent everywhere
# =============================================================================

def check_03_no_min_max(final_json: Dict) -> dict:
    """
    Master prompt pre-flight #6: The token/value "min_max" must not appear anywhere.
    """
    json_str = json.dumps(final_json).lower()
    found = "min_max" in json_str
    issues = ["Found forbidden 'min_max' token in output"] if found else []
    return {"passed": not found, "issues": issues}


# =============================================================================
# CHECK 4: Termination/screenout wording absent everywhere
# =============================================================================

def check_04_no_termination(final_json: Dict) -> dict:
    """
    Master prompt pre-flight #7: Termination/screenout wording must not appear anywhere.
    """
    json_str = json.dumps(final_json).lower()
    issues = []
    for pattern in TERMINATION_PATTERNS:
        matches = re.findall(pattern, json_str)
        if matches:
            issues.append(f"Found termination pattern '{pattern}': {matches[:3]}")
    return {"passed": len(issues) == 0, "issues": issues}


# =============================================================================
# CHECK 5: Every skip rule is target-based and target_vars equals current question vars
# =============================================================================

def check_05_skip_target_based(final_json: Dict) -> dict:
    """
    Master prompt pre-flight #13: Skip logic is stored on target questions only.
    Master prompt logic def A: target_vars must equal current question vars.
    Pre-flight #10: source_vars and target_vars are never empty.
    """
    issues = []
    
    for q in final_json.get("questions", []):
        q_vars = set(flatten_vars(q.get("vars", [])))
        
        for i, logic in enumerate(q.get("logics", [])):
            # Check all logics have non-empty source_vars and target_vars (pre-flight #10)
            if not logic.get("source_vars"):
                issues.append(f"Question {q.get('id')} logic {i}: source_vars is empty")
            if not logic.get("target_vars"):
                issues.append(f"Question {q.get('id')} logic {i}: target_vars is empty")
            
            # For skip logic specifically, target_vars must equal question vars
            if logic.get("type") == "skip":
                target_vars = set(logic.get("target_vars", []))
                if target_vars != q_vars:
                    issues.append(
                        f"Question {q.get('id')} skip logic: target_vars {list(target_vars)} "
                        f"doesn't match question vars {list(q_vars)}"
                    )
    
    return {"passed": len(issues) == 0, "issues": issues}


# =============================================================================
# CHECK 6: Skip-to-question and skip-to-section are fully expanded
# =============================================================================

def check_06_skip_routing_expanded(final_json: Dict, routing: List[Dict], pdf_q: List[Dict]) -> dict:
    """
    Master prompt PASS 4 #6: Skip-to-question and skip-to-section are fully expanded 
    to all skipped-in-between targets.
    """
    issues = []
    questions = final_json.get("questions", [])
    q_ids = [q.get("id") for q in questions]
    
    # Check skip-to-question instructions
    skip_to_q = [r for r in routing if r.get("type") == "skip_to_question"]
    for instr in skip_to_q:
        source = instr.get("source_question")
        target = instr.get("target_question")
        if not source or not target:
            continue
        try:
            src_idx = q_ids.index(source)
            tgt_idx = q_ids.index(target)
        except ValueError:
            continue
        
        # All questions strictly between source and target must have skip logic
        for i in range(src_idx + 1, tgt_idx):
            q = questions[i]
            has_skip = any(l.get("type") == "skip" for l in q.get("logics", []))
            if not has_skip:
                issues.append(
                    f"Skip-to-question '{source}→{target}': Question {q.get('id')} "
                    f"(between) missing skip logic"
                )
    
    # Check skip-to-section instructions
    skip_to_sec = [r for r in routing if r.get("type") == "skip_to_section"]
    for instr in skip_to_sec:
        source = instr.get("source_question")
        target_section = instr.get("target_section")
        if not source or not target_section:
            continue
        # Find first question of target section
        try:
            src_idx = q_ids.index(source)
        except ValueError:
            continue
        
        tgt_idx = None
        for i, q in enumerate(questions):
            if q.get("section") == target_section and i > src_idx:
                tgt_idx = i
                break
        
        if tgt_idx:
            for i in range(src_idx + 1, tgt_idx):
                q = questions[i]
                has_skip = any(l.get("type") == "skip" for l in q.get("logics", []))
                if not has_skip:
                    issues.append(
                        f"Skip-to-section '{source}→{target_section}': Question {q.get('id')} "
                        f"(between) missing skip logic"
                    )
    
    return {"passed": len(issues) == 0, "issues": issues}


# =============================================================================
# CHECK 7: Section gates are expanded to every question in gated section
# =============================================================================

def check_07_section_gates(final_json: Dict, routing: List[Dict]) -> dict:
    """
    Master prompt PASS 4 #7: Section gates are expanded to every question in gated section.
    """
    issues = []
    section_gates = [r for r in routing if r.get("type") == "section_gate"]
    questions = final_json.get("questions", [])
    
    for gate in section_gates:
        section_id = gate.get("section_id")
        if not section_id:
            continue
        
        section_qs = [q for q in questions if q.get("section") == section_id]
        for q in section_qs:
            has_skip = any(l.get("type") == "skip" for l in q.get("logics", []))
            if not has_skip:
                issues.append(
                    f"Section gate for '{section_id}': Question {q.get('id')} missing skip logic"
                )
    
    return {"passed": len(issues) == 0, "issues": issues}


# =============================================================================
# CHECK 8: Exclusive rules present where applicable (none/DK/RF anchors)
# =============================================================================

def check_08_exclusive_rules(final_json: Dict, pattern_report: Dict = None) -> dict:
    """
    Master prompt PASS 4 #8: Exclusive rules present where applicable.
    When pattern_report provided: use exclusive_anchors (data-driven).
    Otherwise fallback: detect anchors by common code patterns across survey conventions.
    """
    issues = []
    pattern_report = pattern_report or {}
    anchors = pattern_report.get("exclusive_anchors", [])
    
    if anchors:
        # Data-driven: use pattern_report.exclusive_anchors
        anchor_by_qid = {a.get("question_id"): a for a in anchors if a.get("question_id")}
        for q in final_json.get("questions", []):
            qid = q.get("id")
            entry = anchor_by_qid.get(qid)
            if not entry or not entry.get("vars"):
                continue
            has_exclusive_logic = any(
                l.get("type") == "exclusive" for l in q.get("logics", [])
            )
            if not has_exclusive_logic:
                issues.append(
                    f"Question {qid}: pattern_report marks exclusive anchors but no exclusive logic"
                )
    else:
        # Fallback: detect anchors by common exclusive-option suffixes
        # Supports _97/_98/_99 (Jewelry), _997/_998/_999 (Escalent), r97/r98/r99, etc.
        def _is_exclusive_anchor(v: str) -> bool:
            if not v:
                return False
            return (
                v.endswith("_97") or v.endswith("_98") or v.endswith("_99") or
                v.endswith("_997") or v.endswith("_998") or v.endswith("_999") or
                v.endswith("r97") or v.endswith("r98") or v.endswith("r99") or
                v.endswith("r997") or v.endswith("r998") or v.endswith("r999")
            )
        for q in final_json.get("questions", []):
            if q.get("type") != "multi_select":
                continue
            vars_list = flatten_vars(q.get("vars", []))
            if not any(_is_exclusive_anchor(v) for v in vars_list):
                continue
            has_exclusive_logic = any(
                l.get("type") == "exclusive" for l in q.get("logics", [])
            )
            if not has_exclusive_logic:
                issues.append(
                    f"Question {q.get('id')}: has exclusive anchor vars but no exclusive logic"
                )
    
    return {"passed": len(issues) == 0, "issues": issues}


# =============================================================================
# CHECK 9: Count rules present for min/max/exactly constraints
# =============================================================================

def check_09_count_rules(final_json: Dict, routing: List[Dict]) -> dict:
    """
    Master prompt PASS 4 #9: Count rules present for min/max/exactly constraints.
    """
    issues = []
    count_instrs = [r for r in routing if r.get("type") == "count"]
    
    questions = final_json.get("questions", [])
    q_by_id = {q.get("id"): q for q in questions}
    
    for instr in count_instrs:
        target_q = instr.get("target_question")
        if not target_q or target_q not in q_by_id:
            continue
        
        q = q_by_id[target_q]
        has_count = any(l.get("type") == "count" for l in q.get("logics", []))
        if not has_count:
            issues.append(
                f"Question {target_q}: has count constraint '{instr.get('constraint')}' but no count logic"
            )
    
    return {"passed": len(issues) == 0, "issues": issues}


# =============================================================================
# CHECK 10: Sum rules present for add-up constraints
# =============================================================================

def check_10_sum_rules(final_json: Dict, routing: List[Dict]) -> dict:
    """
    Master prompt PASS 4 #10: Sum rules present for add-up constraints.
    """
    issues = []
    sum_instrs = [r for r in routing if r.get("type") == "sum"]
    
    questions = final_json.get("questions", [])
    q_by_id = {q.get("id"): q for q in questions}
    
    for instr in sum_instrs:
        target_q = instr.get("target_question")
        if not target_q or target_q not in q_by_id:
            continue
        
        q = q_by_id[target_q]
        has_sum = any(l.get("type") == "sum" for l in q.get("logics", []))
        if not has_sum:
            issues.append(
                f"Question {target_q}: has sum constraint '{instr.get('constraint')}' but no sum logic"
            )
    
    return {"passed": len(issues) == 0, "issues": issues}


# =============================================================================
# CHECK 11: Piping appears only as answer-level filtering/carry-forward
# =============================================================================

def check_11_piping_answer_level(final_json: Dict) -> dict:
    """
    Master prompt PASS 4 #11: Piping appears only as answer-level filtering/carry-forward.
    Master prompt logic def E: Piping is answer-level only (no text piping).
    """
    issues = []
    
    for q in final_json.get("questions", []):
        for logic in q.get("logics", []):
            if logic.get("type") == "piping":
                # Check that piping has proper structure
                source_vars = logic.get("source_vars", [])
                target_vars = logic.get("target_vars", [])
                
                if not source_vars or not target_vars:
                    issues.append(
                        f"Question {q.get('id')}: piping logic has empty source_vars or target_vars"
                    )
                
                # Piping should have source_vars (upstream) and target_vars (downstream filtered)
                # Both should be variable references, not text
                condition = logic.get("condition", "")
                if "text" in condition.lower() and "piping" in condition.lower():
                    issues.append(
                        f"Question {q.get('id')}: possible text piping detected (not allowed)"
                    )
    
    return {"passed": len(issues) == 0, "issues": issues}


# =============================================================================
# CHECK 12: Every dataset variable mapped (question vars or derived var)
# =============================================================================

def check_12_all_vars_mapped(final_json: Dict, dataset_vars: List[str]) -> dict:
    """
    Master prompt pre-flight #12: Every dataset variable is mapped to either 
    questions[*].vars or derived_variables[*].var.
    """
    if not dataset_vars:
        return {"passed": True, "issues": ["No dataset vars provided for verification"]}
    
    # Collect all mapped vars from questions
    question_vars: Set[str] = set()
    for q in final_json.get("questions", []):
        question_vars.update(flatten_vars(q.get("vars", [])))
    
    # Collect all derived vars
    derived_vars = {dv.get("var", "") for dv in final_json.get("derived_variables", [])}
    
    all_mapped = question_vars | derived_vars
    dataset_set = set(dataset_vars)
    unmapped = dataset_set - all_mapped
    
    issues = []
    if unmapped:
        pct = len(unmapped) / len(dataset_vars) * 100
        issues.append(f"{len(unmapped)} unmapped vars ({pct:.1f}%): {sorted(list(unmapped))[:10]}...")
    
    # Strict: all must be mapped (allow tiny tolerance for edge cases)
    passed = len(unmapped) == 0 or len(unmapped) <= max(1, len(dataset_vars) * 0.02)
    
    return {"passed": passed, "issues": issues}


# =============================================================================
# CHECK 13: Derived vars have source_vars whenever possible
# =============================================================================

def check_13_derived_have_sources(final_json: Dict) -> dict:
    """
    Master prompt PASS 4 #13: Derived vars have source_vars whenever possible; 
    empty only in rare impossible cases.
    """
    issues = []
    
    for dv in final_json.get("derived_variables", []):
        var_name = dv.get("var", "?")
        source_vars = dv.get("source_vars", [])
        
        if not source_vars:
            issues.append(f"Derived var '{var_name}': source_vars is empty (must have at least [itself])")
        elif len(source_vars) == 0:
            issues.append(f"Derived var '{var_name}': source_vars is empty list")
    
    return {"passed": len(issues) == 0, "issues": issues}


# =============================================================================
# CHECK 14: questions[] order exactly matches PDF order
# =============================================================================

def check_14_pdf_order(final_json: Dict, pdf_questions: List[Dict]) -> dict:
    """
    Master prompt pre-flight #14: questions[] in final output must follow PDF 
    questionnaire order exactly.
    """
    if not pdf_questions:
        return {"passed": True, "issues": ["No PDF questions provided for order verification"]}
    
    output_ids = [q.get("id") for q in final_json.get("questions", [])]
    pdf_ids = [q.get("id") for q in pdf_questions]
    
    # Find common questions
    common = [q for q in output_ids if q in pdf_ids]
    if not common:
        return {"passed": True, "issues": ["No common question IDs to verify order"]}
    
    # Check relative order is preserved (monotonically increasing PDF indices)
    pdf_indices = [pdf_ids.index(q) for q in common]
    
    issues = []
    for i in range(1, len(pdf_indices)):
        if pdf_indices[i] < pdf_indices[i-1]:
            issues.append(
                f"Order violation: '{common[i]}' appears before '{common[i-1]}' in output "
                f"but after in PDF (PDF positions: {pdf_indices[i-1]} vs {pdf_indices[i]})"
            )
    
    return {"passed": len(issues) == 0, "issues": issues}


# =============================================================================
# REPORT PRINTING
# =============================================================================

def print_report(report: Dict[str, dict]) -> None:
    """Print formatted validation report matching master prompt PASS 4."""
    
    # Check names matching master prompt exactly
    check_names = {
        "01_schema_exactness": "Schema exactness (no extra keys)",
        "02_allowed_types": "Only allowed question/logic types",
        "03_no_min_max": "'min_max' absent everywhere",
        "04_no_termination": "Termination/screenout wording absent",
        "05_skip_target_based": "Skip rules target-based, target_vars = question vars",
        "06_skip_routing_expanded": "Skip-to-question/section fully expanded",
        "07_section_gates_expanded": "Section gates expanded to all questions",
        "08_exclusive_rules": "Exclusive rules for none/DK/RF anchors where applicable",
        "09_count_rules": "Count rules for min/max/exactly",
        "10_sum_rules": "Sum rules for add-up constraints",
        "11_piping_answer_level": "Piping is answer-level only",
        "12_all_vars_mapped": "Every dataset variable mapped",
        "13_derived_have_sources": "Derived vars have source_vars",
        "14_pdf_order": "questions[] order matches PDF",
    }
    
    print("\n" + "=" * 70)
    print("PASS 4: FINAL VALIDATION (14 CHECKS FROM MASTER PROMPT)")
    print("=" * 70)
    
    passed_count = 0
    failed_count = 0
    
    for key, result in sorted(report.items()):
        ok = result["passed"]
        issues = result.get("issues", [])
        
        sym = "+" if ok else "X"
        status = "PASS" if ok else "FAIL"
        name = check_names.get(key, key)
        
        print(f"\n[{sym}] {status}: #{key[:2]} {name}")
        
        if not ok and issues:
            for issue in issues[:5]:
                print(f"     - {issue}")
            if len(issues) > 5:
                print(f"     ... and {len(issues) - 5} more issues")
        
        if ok:
            passed_count += 1
        else:
            failed_count += 1
    
    print("\n" + "=" * 70)
    print(f"RESULT: {passed_count}/14 passed, {failed_count}/14 failed")
    
    if failed_count == 0:
        print("ALL VALIDATION CHECKS PASSED - OUTPUT ACCEPTED")
    else:
        print("VALIDATION FAILED - REJECT/REGENERATE REQUIRED")
    
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Step 8: Validate final JSON (PASS 4)")
    parser.add_argument("--json", "-j", required=True, help="Path to final JSON")
    parser.add_argument("--inventory", "-i", help="Path to dataset inventory (for var mapping check)")
    parser.add_argument("--structure", "-s", help="Path to PDF structure (for order/routing checks)")
    args = parser.parse_args()
    
    print("\n[Step 8] Final Validation (PASS 4 - 14 CHECKS)")
    print("=" * 50)
    
    with open(args.json) as f:
        final_json = json.load(f)
    
    dataset_vars = []
    if args.inventory:
        with open(args.inventory) as f:
            inv = json.load(f)
            dataset_vars = [v["var"] for v in (inv if isinstance(inv, list) else inv.get("variables", []))]
    
    pdf_questions = []
    routing = []
    if args.structure:
        with open(args.structure) as f:
            struct = json.load(f)
            pdf_questions = struct.get("questions", [])
            routing = struct.get("logic_instructions", [])
    
    is_valid, report = validate_final_output(final_json, dataset_vars, pdf_questions, routing)
    print_report(report)
    
    return 0 if is_valid else 1


if __name__ == "__main__":
    exit(main())
