#!/usr/bin/env python3
"""
Step 3: Question-to-Variable Mapping (PASS 2)

Maps each question to dataset variables using metadata as ground truth.
Detects multi-select sets, grid/array blocks, other-specify pairs, loop/repeat blocks.
Uses evidence threshold: map confidently when at least 2 signals support.

Usage:
    python s3_mapping.py --inventory s2_result.json --structure s1_result.json --output s3_result.json
"""

import json
import os
import argparse
from typing import Dict, List

from logic_platform.utils import ManusAPIClient, extract_json_from_task
from logic_platform.opus_utils import call_opus_json, estimate_opus_cost


def map_questions_to_variables(
    dataset_inventory: List[Dict],
    questionnaire_structure: Dict,
    show_progress: bool = True,
    engine: str = "manus",
) -> tuple:
    """
    Map questions to dataset variables.
    
    Args:
        engine: "manus" or "opus"
    
    Returns:
        (result_dict, cost_info) - cost_info is {"credits": N} or {"input_tokens": N, "output_tokens": N}
    """
    if engine == "opus":
        return _map_with_opus(dataset_inventory, questionnaire_structure, show_progress)
    return _map_with_manus(dataset_inventory, questionnaire_structure, show_progress)


def _map_with_opus(
    dataset_inventory: List[Dict],
    questionnaire_structure: Dict,
    show_progress: bool,
) -> tuple:
    """Use Claude Opus 4.6 on Vertex AI."""
    prompt = _build_mapping_prompt(len(dataset_inventory), len(questionnaire_structure.get("questions", [])))
    # Opus variant: respond with JSON, not save to file
    prompt = prompt.replace("INPUT FILES (ATTACHED)", "INPUT DATA (provided below as JSON)")
    prompt = prompt.replace(
        "You MUST save your output to a file named: mapping_output.json\n\nThe file MUST have this EXACT structure:",
        "Respond with ONLY a valid JSON object. No markdown, no code blocks, no explanation. Use this EXACT structure:"
    )
    prompt = prompt.replace(
        "After mapping all questions, pattern discovery, and verification, SAVE your result to: mapping_output.json\nThe file must contain valid JSON with \"questions_mapped\" and \"unmapped_vars\" arrays.",
        "After mapping all questions, pattern discovery, and verification, respond with the JSON object containing \"questions_mapped\" and \"unmapped_vars\" arrays."
    )
    result, usage = call_opus_json(
        prompt,
        {
            "dataset_inventory.json": dataset_inventory,
            "questionnaire.json": questionnaire_structure,
        },
        show_progress=show_progress,
    )
    if isinstance(result, list):
        result = {"questions_mapped": result, "unmapped_vars": []}
    elif isinstance(result, dict):
        questions = result.get("questions_mapped") or result.get("questions") or result.get("mapped_questions") or []
        unmapped = result.get("unmapped_vars") or result.get("unmapped_variables") or result.get("unmapped") or []
        result = {"questions_mapped": questions, "unmapped_vars": unmapped}
    if show_progress:
        print(f"  Mapping complete:")
        print(f"    - Questions mapped: {len(result.get('questions_mapped', []))}")
        print(f"    - Unmapped vars: {len(result.get('unmapped_vars', []))}")
        print(f"    - Tokens: {usage['input_tokens']} in, {usage['output_tokens']} out (~${estimate_opus_cost(usage['input_tokens'], usage['output_tokens']):.4f})")
    return result, usage


def _map_with_manus(
    dataset_inventory: List[Dict],
    questionnaire_structure: Dict,
    show_progress: bool,
) -> tuple:
    """Use Manus to map questions to dataset variables."""
    client = ManusAPIClient()
    
    # Upload with explicit file names
    if show_progress:
        print("  Uploading dataset_inventory.json...")
    inventory_upload = client.upload_json(dataset_inventory, "dataset_inventory.json")
    
    if show_progress:
        print("  Uploading questionnaire.json...")
    questionnaire_upload = client.upload_json(questionnaire_structure, "questionnaire.json")
    
    prompt = _build_mapping_prompt(len(dataset_inventory), len(questionnaire_structure.get("questions", [])))
    
    if show_progress:
        print("  Creating mapping task...")
    
    task_result = client.create_task(
        prompt=prompt,
        attachments=[
            {"file_id": inventory_upload.file_id},
            {"file_id": questionnaire_upload.file_id}
        ],
        agent_profile="manus-1.6",
        task_mode="agent"
    )
    
    if show_progress:
        print(f"  Task created: {task_result.task_id}")
        print(f"  Task URL: {task_result.task_url}")
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
    
    # Normalize result to expected format {"questions_mapped": [...], "unmapped_vars": [...]}
    if isinstance(result, list):
        # Direct list of questions
        result = {"questions_mapped": result, "unmapped_vars": []}
    elif isinstance(result, dict):
        # Handle various key names the API might return
        questions = (
            result.get("questions_mapped") or 
            result.get("questions") or 
            result.get("mapped_questions") or
            []
        )
        unmapped = (
            result.get("unmapped_vars") or 
            result.get("unmapped_variables") or 
            result.get("unmapped") or
            []
        )
        result = {"questions_mapped": questions, "unmapped_vars": unmapped}
    
    if show_progress:
        print(f"  Mapping complete:")
        print(f"    - Questions mapped: {len(result.get('questions_mapped', []))}")
        print(f"    - Unmapped vars: {len(result.get('unmapped_vars', []))}")
    
    credits = final_task.get("credit_usage") or 0
    return result, {"credits": credits}


def _build_mapping_prompt(num_vars: int, num_questions: int) -> str:
    """Build the mapping prompt for Manus - PASS 2 from master prompt.
    
    Data is provided as file attachments, not embedded in prompt.
    """
    return f'''You are an expert survey programmer + data architect. Your task is PASS 2: MATCHING + STRUCTURE DISCOVERY.

=============================================================================
INPUT FILES (ATTACHED)
=============================================================================
1. dataset_inventory.json - {num_vars} variables, each with: var, label, values, type, order
2. questionnaire.json - {num_questions} questions from PDF with: id, section_id, text, type, order

FIRST: Read both files completely.

=============================================================================
OUTPUT REQUIREMENT
=============================================================================
You MUST save your output to a file named: mapping_output.json

The file MUST have this EXACT structure:
{{
  "questions_mapped": [
    {{
      "id": "<question_id>",
      "section": "A", 
      "text": "Full question text",
      "type": "single_select|multi_select|grid|numeric|open_text",
      "vars": ["VAR1"] or [["row1_vars"], ["row2_vars"]] for grids,
      "answers": {{}},
      "logics": []
    }}
  ],
  "unmapped_vars": ["VAR_A", "VAR_B"]
}}

=============================================================================
QUESTION TYPE RULES (STRICT - FROM MASTER PROMPT)
=============================================================================

1) single_select: exactly 1 dataset var
2) numeric: exactly 1 dataset var  
3) open_text: exactly 1 dataset var
4) multi_select: list of dataset vars (multiple binary columns)
5) grid: vars is LIST OF LISTS
   - each inner list is one ROW containing dataset vars across columns
   - preserve questionnaire row order (reorder if dataset storage differs)

=============================================================================
EVIDENCE-BASED MAPPING (USE AT LEAST 2 SIGNALS)
=============================================================================

Use these evidence signals to map questions to variables:

A) VARIABLE NAMING PATTERNS:
   - Shared stems/prefixes indicate multi-select groups
   - Numeric suffixes indicating set membership
   - Row/column patterns for grids (two dimensions in naming)
   
   GROUPING AND COMPLETENESS:
   - When you identify a naming pattern, find ALL variables matching that pattern in dataset_inventory
   - Verify completeness: found variables vs. all matching variables
   - If missing variables found, add them to the question's vars array
   - PRESERVE from input: grid_rows, grid_columns, answer_options (when present on questionnaire questions)

B) VARIABLE LABELS:
   - Label text matches or closely resembles question text
   - Label contains question ID reference

C) VALUE LABELS:
   - Value labels match answer options from questionnaire
   - Scale points match (1-5, 1-7, 1-10, etc.)

D) ORDER/ADJACENCY:
   - Dataset order matches questionnaire order
   - Adjacent variables in dataset belong to same question

EVIDENCE THRESHOLD: Map confidently when at least TWO signals support mapping.
If weak evidence (only 1 signal or ambiguous), add to unmapped_vars for orphan pass.

=============================================================================
STRUCTURE DETECTION (DATA DETERMINES TYPE)
=============================================================================

IMPORTANT: The DATA STRUCTURE determines the actual question type, not the PDF!
The PDF may say "grid" but data could be multi-select, or vice versa.

HOW TO DETECT FROM DATA:

1) MULTI-SELECT (1-dimensional, flat list):
   - Variables share prefix with option suffixes; each var = one option, binary (0/1)
   - vars = flat list of all option variables
   - Use the pattern to search dataset_inventory for all matching variables to ensure completeness

2) GRID (2-dimensional, rows × columns):
   - Variables: <VAR>_r1_c1, <VAR>_r1_c2, <VAR>_r2_c1, <VAR>_r2_c2 (row AND column pattern)
   - OR: <VAR>_<Row1>_<Col1>, <VAR>_<Row1>_<Col2>, <VAR>_<Row2>_<Col1>
   - Must have TWO dimensions evident in naming
   - vars = [[row1_vars], [row2_vars], ...] (list of lists)
   - Each inner list = one row (one item evaluated across all columns)

CRITICAL - TYPE OVERRIDE RULES:
- DATA STRUCTURE WINS over PDF description
- Grid requires BOTH row AND column dimensions in variable names (r1_c1, r1_c2, r2_c1)
- If variables have only row pattern (r1, r2, r3) with NO column dimension → MULTI_SELECT
- If PDF says "grid" but data has only single-dimension pattern → override to MULTI_SELECT
- If PDF says "multi_select" but data has true 2D pattern → override to GRID

DETECTION PRINCIPLE:
- Single dimension pattern (suffixes only, or rows only) → multi_select
- Two dimension pattern (rows AND columns both present) → grid

3) OTHER-SPECIFY PAIRS:
   - Main question variable + "_OTH" or "_OTHER" or "_SPECIFY" suffix
   - Text field paired with categorical question

4) LOOP/REPEAT BLOCKS:
   - Variables with iteration suffix (_1, _2, _3 representing loop iterations)
   - Same question asked multiple times for different items

=============================================================================
CRITICAL RULES
=============================================================================

1) Preserve EXACT question order from questionnaire.json
2) Every question MUST have "answers": {{}} and "logics": []
3) DATA STRUCTURE determines type - override PDF type if data pattern differs
4) For grids: vars MUST be list of lists (each inner list = one row)
5) For multi_select: vars MUST be flat list (not nested)
6) Only use ACTUAL variable names from dataset_inventory.json
7) Preserve grid_rows, grid_columns, answer_options from questionnaire input

=============================================================================
IMPORTANT: MAPPING ENABLES LOGIC
=============================================================================

The "vars" array you create for each question is CRITICAL for downstream logic.
After this step, ALL logic will reference DATA VARIABLES (not question IDs).
Accurate mapping is essential - every question needs correct vars from the data.

=============================================================================
CRITICAL: ACCOUNT FOR EVERY SINGLE VARIABLE
=============================================================================

YOU MUST ACCOUNT FOR 100% OF VARIABLES in the dataset.
Every variable MUST end up in EITHER:
- A question's vars array (mapped), OR
- The unmapped_vars array (for resolution in next step)

VALIDATION:
  count(mapped vars) + count(unmapped_vars) == count(dataset_inventory vars)

If this doesn't balance, you've lost variables. Find them.

DO NOT skip variables just because they don't match questionnaire questions.
If you can't confidently map a variable to a question, PUT IT IN unmapped_vars.
The next step will classify these as derived variables, system vars, etc.

=============================================================================
VERIFICATION AND PATTERN DISCOVERY PASS
=============================================================================

After initial mapping from PDF structure, perform these steps:

1. PATTERN DISCOVERY:
   - Scan dataset_inventory for common multi-select patterns:
     * Variables with sequential suffixes (_r1, _r2, _r3 or _1, _2, _3)
     * Variables sharing prefixes with numeric option suffixes
   - For each pattern cluster found:
     * Check if variables are already mapped to a question
     * If unmapped, investigate variable labels for common question text
     * If labels suggest a coherent question, create a new question mapping
   - This helps discover questions that may not be clearly represented in PDF structure

2. COMPREHENSIVE VERIFICATION (BEFORE SAVING):
   - Count all vars in questions_mapped
   - Count unmapped_vars
   - Sum must equal total vars in dataset_inventory
   - If not equal, find the missing vars and add to unmapped_vars
   - For each multi-select question: verify you found ALL variables matching its pattern
   - If pattern suggests sequential numbering, verify no gaps were missed
   - Only save after verification is complete

=============================================================================
FINAL STEP - SAVE OUTPUT
=============================================================================

After mapping all questions, pattern discovery, and verification, SAVE your result to: mapping_output.json
The file must contain valid JSON with "questions_mapped" and "unmapped_vars" arrays.
'''


def main():
    parser = argparse.ArgumentParser(description="Step 3: Map questions to variables")
    parser.add_argument("--inventory", "-i", required=True, help="Path to dataset inventory JSON (from Step 2)")
    parser.add_argument("--structure", "-s", required=True, help="Path to PDF structure JSON (from Step 1)")
    parser.add_argument("--output", "-o", default="output/s3_mapping.json", help="Output JSON file")
    parser.add_argument("--quiet", "-q", action="store_true", help="Reduce output")
    args = parser.parse_args()
    
    from dotenv import load_dotenv
    load_dotenv()
    
    print("\n[Step 3] Question-to-Variable Mapping (PASS 2)")
    print("=" * 50)
    
    with open(args.inventory) as f:
        inv_data = json.load(f)
    inventory = inv_data if isinstance(inv_data, list) else inv_data.get("variables", [])
    
    with open(args.structure) as f:
        structure = json.load(f)
    
    result, _ = map_questions_to_variables(inventory, structure, show_progress=not args.quiet)
    
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)
    
    print(f"\nResult saved to: {args.output}")


if __name__ == "__main__":
    main()
