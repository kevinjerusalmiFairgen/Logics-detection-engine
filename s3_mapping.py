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

from utils import ManusAPIClient, extract_json_from_task


def map_questions_to_variables(
    dataset_inventory: List[Dict],
    questionnaire_structure: Dict,
    show_progress: bool = True
) -> Dict:
    """
    Use Manus to map questions to dataset variables.
    Uploads data as files instead of embedding in prompt.
    
    Returns:
        Dict with: questions_mapped, unmapped_vars
    """
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
        max_wait=1200,
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
    
    return result


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
      "id": "Q1",
      "section": "A", 
      "text": "Full question text",
      "type": "single_select|multi_select|grid|numeric|open_text|numeric_grid",
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
6) numeric_grid: same as grid but for numeric inputs

=============================================================================
EVIDENCE-BASED MAPPING (USE AT LEAST 2 SIGNALS)
=============================================================================

Use these evidence signals to map questions to variables:

A) VARIABLE NAMING PATTERNS:
   - Shared stems/prefixes (<VAR>_1, <VAR>_2, <VAR>_3 → multi-select for that question)
   - Numeric suffixes indicating set membership
   - Row/column patterns for grids (<VAR>_r1_c1, <VAR>_r1_c2, <VAR>_r2_c1)
   - Terminal codes: _97, _98, _99 often indicate exclusive anchors (None/DK/RF)

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
   - Variables: <VAR>_1, <VAR>_2, <VAR>_3, <VAR>_97 (shared prefix + option suffix)
   - Each variable = one option, binary coded (0/1 selected/not)
   - vars = ["<VAR>_1", "<VAR>_2", "<VAR>_3", "<VAR>_97"] (flat list)
   - Include exclusive anchors (_97/_98/_99)

2) GRID (2-dimensional, rows × columns):
   - Variables: <VAR>_r1_c1, <VAR>_r1_c2, <VAR>_r2_c1, <VAR>_r2_c2 (row AND column pattern)
   - OR: <VAR>_<Row1>_<Col1>, <VAR>_<Row1>_<Col2>, <VAR>_<Row2>_<Col1>
   - Must have TWO dimensions evident in naming
   - vars = [[row1_vars], [row2_vars], ...] (list of lists)
   - Each inner list = one row (one item rated on all attributes)

CRITICAL - TYPE OVERRIDE RULES:
- If PDF says "grid" but data has only <VAR>_1, <VAR>_2, <VAR>_3 pattern → it's MULTI_SELECT
- If PDF says "multi_select" but data has <VAR>_r1_c1, <VAR>_r1_c2 pattern → it's GRID
- DATA STRUCTURE WINS over PDF description
- Grid requires BOTH row AND column dimensions in variable names

DETECTION EXAMPLES:
- "<VAR>_1, <VAR>_2, <VAR>_3" = multi_select (single dimension, option suffixes)
- "<VAR>_r1_c1, <VAR>_r1_c2, <VAR>_r2_c1" = grid (two dimensions: r1/r2 AND c1/c2)
- "<VAR>_<Item1>, <VAR>_<Item2>, <VAR>_<Item3>" = multi_select (items, not rows×cols)
- "<VAR>_<Item1>_<Attr1>, <VAR>_<Item1>_<Attr2>, <VAR>_<Item2>_<Attr1>" = grid (item × attribute)

3) OTHER-SPECIFY PAIRS:
   - Main question variable + "_OTH" or "_OTHER" or "_SPECIFY" suffix
   - Text field paired with categorical question

4) LOOP/REPEAT BLOCKS:
   - Variables with iteration suffix (_1, _2, _3 representing loop iterations)
   - Same question asked multiple times for different items

5) EXCLUSIVE ANCHORS:
   - Variables ending in _97, _98, _99 within multi-select
   - Represent "None of the above", "Don't know", "Refuse to answer"
   - MUST be included in the multi-select vars list

=============================================================================
CRITICAL RULES
=============================================================================

1) Preserve EXACT question order from questionnaire.json
2) Every question MUST have "answers": {{}} and "logics": []
3) DATA STRUCTURE determines type - override PDF type if data pattern differs
4) For grids: vars MUST be list of lists (each inner list = one row)
5) For multi_select: vars MUST be flat list (not nested)
6) Only use ACTUAL variable names from dataset_inventory.json
7) Include exclusive anchors (_97/_98/_99) in multi-select vars

=============================================================================
IMPORTANT: MAPPING ENABLES LOGIC
=============================================================================

The "vars" array you create for each question is CRITICAL for downstream logic.
After this step, ALL logic will reference DATA VARIABLES (not question IDs).

Example: If QA asks a demographic question and maps to variable "<DEMO_VAR>":
- Question ID: "QA" (from PDF)
- vars: ["<DEMO_VAR>"] (from data)
- Later logic will say: "if <DEMO_VAR> == 1" NOT "if QA == 1"

So accurate mapping is essential - every question needs correct vars from the data.

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
FINAL STEP - SAVE OUTPUT
=============================================================================

After mapping all questions, SAVE your result to: mapping_output.json
The file must contain valid JSON with "questions_mapped" and "unmapped_vars" arrays.

BEFORE SAVING, VERIFY:
- Count all vars in questions_mapped
- Count unmapped_vars
- Sum must equal total vars in dataset_inventory
- If not equal, find the missing vars and add to unmapped_vars
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
    
    result = map_questions_to_variables(inventory, structure, show_progress=not args.quiet)
    
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)
    
    print(f"\nResult saved to: {args.output}")


if __name__ == "__main__":
    main()
