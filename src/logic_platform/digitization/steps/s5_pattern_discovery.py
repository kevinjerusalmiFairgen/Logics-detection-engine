#!/usr/bin/env python3
"""
Step 5: Pattern Discovery (PASS 2C)

Detective pass: find exclusive anchors, recode relationships, and multi-select
groups from questionnaire + metadata. Derive all patterns from the survey's own
data. Do not use preset keyword lists or code conventions.
Expand discovered patterns across similar structures.

Usage:
    python s5_pattern_discovery.py --questions s4_result.json --inventory s2_result.json --output pattern_report.json
"""

import json
import os
import argparse
from typing import Dict, List

from logic_platform.utils import ManusAPIClient, extract_json_from_task
from logic_platform.opus_utils import call_opus_json, estimate_opus_cost


def run_pattern_discovery(
    questions_updated: List[Dict],
    dataset_inventory: List[Dict],
    logic_instructions: List[Dict],
    derived_variables: List[Dict],
    pdf_questions: List[Dict] = None,
    show_progress: bool = True,
    engine: str = "manus",
) -> tuple:
    """
    Run pattern discovery task.
    
    Returns:
        (pattern_report dict, cost_info) - cost_info is {"credits": N} or {"input_tokens": N, "output_tokens": N}
    """
    if engine == "opus":
        return _pattern_with_opus(questions_updated, dataset_inventory, logic_instructions, derived_variables, show_progress)
    return _pattern_with_manus(questions_updated, dataset_inventory, logic_instructions, derived_variables, show_progress)


def _pattern_with_opus(
    questions_updated: List[Dict],
    dataset_inventory: List[Dict],
    logic_instructions: List[Dict],
    derived_variables: List[Dict],
    show_progress: bool,
) -> tuple:
    """Use Claude Opus 4.6 on Vertex AI."""
    prompt = _build_pattern_discovery_prompt(len(questions_updated), len(dataset_inventory), len(logic_instructions))
    prompt = prompt.replace("INPUT FILES (ATTACHED)", "INPUT DATA (provided below as JSON)")
    prompt = prompt.replace(
        "OUTPUT: SAVE TO pattern_report.json\n\nThe file MUST have this structure:",
        "Respond with ONLY a valid JSON object. No markdown, no code blocks. Use this structure:"
    )
    result, usage = call_opus_json(
        prompt,
        {
            "questions_updated.json": questions_updated,
            "dataset_inventory.json": dataset_inventory,
            "logic_instructions.json": logic_instructions,
            "derived_variables.json": derived_variables or [],
        },
        show_progress=show_progress,
    )
    report = result.get("pattern_report", result) if isinstance(result, dict) else {}
    if show_progress:
        print(f"  Tokens: {usage['input_tokens']} in, {usage['output_tokens']} out (~${estimate_opus_cost(usage['input_tokens'], usage['output_tokens']):.4f})")
    return report, usage


def _pattern_with_manus(
    questions_updated: List[Dict],
    dataset_inventory: List[Dict],
    logic_instructions: List[Dict],
    derived_variables: List[Dict],
    show_progress: bool,
) -> tuple:
    """Use Manus pattern discovery."""
    client = ManusAPIClient()
    
    if show_progress:
        print("  Uploading questions_updated.json...")
    q_upload = client.upload_json(questions_updated, "questions_updated.json")
    
    if show_progress:
        print("  Uploading dataset_inventory.json...")
    inv_upload = client.upload_json(dataset_inventory, "dataset_inventory.json")
    
    if show_progress:
        print("  Uploading logic_instructions.json...")
    li_upload = client.upload_json(logic_instructions, "logic_instructions.json")
    
    if show_progress:
        print("  Uploading derived_variables.json...")
    dv_upload = client.upload_json(derived_variables or [], "derived_variables.json")
    
    prompt = _build_pattern_discovery_prompt(
        len(questions_updated), len(dataset_inventory), len(logic_instructions)
    )
    
    if show_progress:
        print("  Creating pattern discovery task...")
    
    task_result = client.create_task(
        prompt=prompt,
        attachments=[
            {"file_id": q_upload.file_id},
            {"file_id": inv_upload.file_id},
            {"file_id": li_upload.file_id},
            {"file_id": dv_upload.file_id},
        ],
        agent_profile="manus-1.6",
        task_mode="agent"
    )
    
    if show_progress:
        print(f"  Task created: {task_result.task_id}")
        print("  Waiting for completion...")
    
    final_task = client.poll_task_completion(
        task_result.task_id,
        poll_interval=10,
        max_wait=3600,
        show_thinking=show_progress
    )
    
    if final_task.get("status") != "completed":
        raise Exception(f"Task failed: {final_task.get('status')}")
    
    result = extract_json_from_task(client, final_task)
    report = result.get("pattern_report", result) if isinstance(result, dict) else {}
    
    credits = final_task.get("credit_usage", 0)
    return report, {"credits": credits}


def _build_pattern_discovery_prompt(num_questions: int, num_vars: int, num_instructions: int) -> str:
    """Build the pattern discovery prompt. Agnostic, no real examples."""
    return f'''You are an expert survey programmer acting as a logic detective. Your task is PASS 2C: PATTERN DISCOVERY.

=============================================================================
INPUT FILES (ATTACHED)
=============================================================================
1. questions_updated.json - {num_questions} questions with vars mapped (includes grid_rows, grid_columns when available)
2. dataset_inventory.json - {num_vars} variables with var, label, values, type
3. logic_instructions.json - {num_instructions} raw instructions from PDF
4. derived_variables.json - recodes and derived vars

Read ALL files first.

=============================================================================
PRINCIPLE: DATA-DRIVEN, NO PRESCRIPTION
=============================================================================

Do NOT use preset keyword lists, code conventions, or language assumptions.
Derive ALL patterns from the survey's own content:
- Questionnaire text, option labels, logic instructions
- Variable labels, value labels, naming patterns
- Position (last option, second-to-last), structure (grid rows, multi-select order)
- Correlate across sources to confirm

=============================================================================
YOUR TASK: DISCOVER AND EXPAND PATTERNS
=============================================================================

1) FIND IN QUESTIONNAIRE (qnr):
   - logic_instructions: exclusive_options, piping, count, sum, etc.
   - Question text, grid_rows, grid_columns, any visible option labels
   - Explicit mentions of exclusivity, mutual exclusion, recodes, groupings

2) FIND IN METADATA:
   - Variable labels and value labels
   - Naming patterns (stems, prefixes, suffixes, numeric codes)
   - Adjacency and order in the dataset
   - Match vars to question/option text by label or position

3) INFER PATTERNS FROM WHAT YOU FOUND:
   - For each confirmed exclusive option: What evidence? (qnr text, var label, position, logic_instruction)
   - Extract the phrase or code pattern used in THIS survey
   - For recodes: source vars, target, derivation pattern
   - For multi-select groups: var stems, structure, which options (if any) are exclusive within the group
   - Record learned phrases and codes as they appear in THIS survey

4) EXPAND PATTERNS:
   - Apply discovered patterns to other questions with similar structure
   - Same var stem family, same grid layout, same question block
   - When you find a pattern in one place, scan for matching structures elsewhere
   - Add all applications to the output

=============================================================================
OUTPUT: SAVE TO pattern_report.json
=============================================================================

The file MUST have this structure:
{{
  "exclusive_anchors": [
    {{
      "question_id": "<id>",
      "vars": ["<var1>", "<var2>"],
      "evidence": ["<source>"],
      "learned_phrase": "<phrase from this survey or null>"
    }}
  ],
  "learned_exclusive_phrases": ["<phrase1>", "<phrase2>"],
  "learned_exclusive_codes": ["<code_pattern1>", "<code_pattern2>"],
  "recode_patterns": [
    {{
      "target_var": "<var>",
      "source_vars": ["<var1>", "<var2>"],
      "evidence": ["<source>"]
    }}
  ],
  "multiselect_groups": [
    {{
      "question_id": "<id>",
      "vars": ["<var1>", "<var2>"],
      "exclusive_vars": ["<var>"],
      "structure_note": "<brief note>"
    }}
  ],
  "expanded_applications": [
    {{
      "pattern_type": "exclusive|recode|multiselect",
      "applied_to": "<question_id or var>",
      "evidence": "<why expanded>"
    }}
  ]
}}

CRITICAL:
- exclusive_anchors: every multi_select/grid question that has exclusive options must have an entry
- learned_phrases and learned_codes: derived from THIS survey only, not from external lists
- evidence: cite the source (logic_instruction, dataset_label, position_last, grid_rows, question_text, etc.)
- expanded_applications: where you applied a pattern from one place to another similar place
'''


def main():
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Step 5: Pattern Discovery")
    parser.add_argument("--questions", "-q", required=True, help="Path to questions JSON (from Step 4)")
    parser.add_argument("--inventory", "-i", required=True, help="Path to dataset inventory (from Step 2)")
    parser.add_argument("--instructions", help="Path to logic instructions (from Step 1)")
    parser.add_argument("--derived", help="Path to derived variables (from Step 4)")
    parser.add_argument("--pdf-questions", help="Path to PDF questions (from Step 1)")
    parser.add_argument("--output", "-o", default="output/pattern_report.json", help="Output path")
    parser.add_argument("--engine", "-e", choices=["opus", "manus"], default="manus")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    
    with open(args.questions) as f:
        data = json.load(f)
    questions = data.get("questions_updated", data.get("questions", []))
    
    with open(args.inventory) as f:
        inv_data = json.load(f)
    inventory = inv_data.get("variables", inv_data)
    
    logic = []
    if args.instructions and os.path.exists(args.instructions):
        with open(args.instructions) as f:
            struct = json.load(f)
        logic = struct.get("logic_instructions", [])
    
    derived = []
    if args.derived and os.path.exists(args.derived):
        with open(args.derived) as f:
            res = json.load(f)
        derived = res.get("derived_variables", [])
    
    pdf_q = []
    if args.pdf_questions and os.path.exists(args.pdf_questions):
        with open(args.pdf_questions) as f:
            pdf_data = json.load(f)
        pdf_q = pdf_data.get("questions", [])
    
    report, credits = run_pattern_discovery(
        questions, inventory, logic, derived, pdf_q, show_progress=not args.quiet, engine=args.engine
    )
    
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)
    
    print(f"\nPattern report saved to: {args.output}")
    print(f"Credits used: {credits}")


if __name__ == "__main__":
    main()
