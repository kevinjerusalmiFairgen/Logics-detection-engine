#!/usr/bin/env python3
"""
Step 4: Unmapped Variable Resolution (PASS 2B - ORPHAN CLOSURE)

Resolves EVERY unmapped dataset variable in strict order.
MUST reach zero unmapped variables (Gate 3).

Resolution order:
1) Attach to existing structure/group
2) Match to single question by evidence
3) Classify as derived variable
4) Last resort: mark as unused derived

Usage:
    python s4_resolve.py --mapped s3_result.json --inventory s2_result.json --output s4_result.json
"""

import json
import os
import argparse
from typing import Dict, List

from logic_platform.utils import ManusAPIClient, extract_json_from_task
from logic_platform.opus_utils import call_opus_json, estimate_opus_cost


def resolve_unmapped_variables(
    questions_mapped: List[Dict],
    unmapped_vars: List[str],
    dataset_inventory: List[Dict],
    show_progress: bool = True,
    engine: str = "manus",
) -> tuple:
    """
    Resolve unmapped variables (PASS 2B).
    
    Returns:
        (result_dict, cost_info) - cost_info is {"credits": N} or {"input_tokens": N, "output_tokens": N}
    """
    if not unmapped_vars:
        if show_progress:
            print("  No unmapped variables to resolve")
        return {
            "derived_variables": [],
            "questions_updated": questions_mapped
        }, {"credits": 0} if engine == "manus" else {"input_tokens": 0, "output_tokens": 0}

    if engine == "opus":
        return _resolve_with_opus(questions_mapped, unmapped_vars, dataset_inventory, show_progress)
    return _resolve_with_manus(questions_mapped, unmapped_vars, dataset_inventory, show_progress)


def _resolve_with_opus(
    questions_mapped: List[Dict],
    unmapped_vars: List[str],
    dataset_inventory: List[Dict],
    show_progress: bool,
) -> tuple:
    """Use Claude Opus 4.6 on Vertex AI."""
    unmapped_metadata = [v for v in dataset_inventory if v["var"] in unmapped_vars]
    unmapped_data = {"unmapped_vars": unmapped_vars, "unmapped_metadata": unmapped_metadata}
    prompt = _build_resolution_prompt(len(questions_mapped), len(unmapped_vars))
    prompt = prompt.replace("INPUT FILES (ATTACHED)", "INPUT DATA (provided below as JSON)")
    prompt = prompt.replace(
        "You MUST save your output to a file named: resolution_output.json\n\nThe file MUST have this EXACT structure:",
        "Respond with ONLY a valid JSON object. No markdown, no code blocks. Use this EXACT structure:"
    )
    prompt = prompt.replace(
        "After validation passes, SAVE your result to: resolution_output.json\nThe file must contain valid JSON with \"derived_variables\" and \"questions_updated\" arrays.",
        "After validation passes, respond with the JSON object containing \"derived_variables\" and \"questions_updated\" arrays."
    )
    result, usage = call_opus_json(
        prompt,
        {"questions_mapped.json": questions_mapped, "unmapped_vars.json": unmapped_data},
        show_progress=show_progress,
    )
    derived = result.get("derived_variables") or result.get("derived") or []
    questions = result.get("questions_updated") or result.get("questions") or result.get("questions_mapped") or []
    result = {"derived_variables": derived, "questions_updated": questions}
    if show_progress:
        print(f"  Resolution complete:")
        print(f"    - Derived variables: {len(derived)}")
        print(f"    - Questions updated: {len(questions)}")
        print(f"    - Tokens: {usage['input_tokens']} in, {usage['output_tokens']} out (~${estimate_opus_cost(usage['input_tokens'], usage['output_tokens']):.4f})")
    return result, usage


def _resolve_with_manus(
    questions_mapped: List[Dict],
    unmapped_vars: List[str],
    dataset_inventory: List[Dict],
    show_progress: bool,
) -> tuple:
    """Use Manus to resolve unmapped variables."""
    client = ManusAPIClient()
    
    # Get metadata for unmapped vars
    unmapped_metadata = [v for v in dataset_inventory if v["var"] in unmapped_vars]
    
    if show_progress:
        print(f"  Resolving {len(unmapped_vars)} unmapped variables...")
    
    # Upload with explicit file names
    if show_progress:
        print("  Uploading questions_mapped.json...")
    questions_upload = client.upload_json(questions_mapped, "questions_mapped.json")
    
    if show_progress:
        print("  Uploading unmapped_vars.json...")
    unmapped_data = {"unmapped_vars": unmapped_vars, "unmapped_metadata": unmapped_metadata}
    unmapped_upload = client.upload_json(unmapped_data, "unmapped_vars.json")
    
    prompt = _build_resolution_prompt(len(questions_mapped), len(unmapped_vars))
    
    if show_progress:
        print("  Creating resolution task...")
    
    task_result = client.create_task(
        prompt=prompt,
        attachments=[
            {"file_id": questions_upload.file_id},
            {"file_id": unmapped_upload.file_id}
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
    
    # Normalize result to expected format
    if isinstance(result, dict):
        derived = (
            result.get("derived_variables") or 
            result.get("derived") or 
            []
        )
        questions = (
            result.get("questions_updated") or 
            result.get("questions") or 
            result.get("questions_mapped") or
            []
        )
        result = {"derived_variables": derived, "questions_updated": questions}
    elif isinstance(result, list):
        # Assume list of questions
        result = {"derived_variables": [], "questions_updated": result}
    
    if show_progress:
        print(f"  Resolution complete:")
        print(f"    - Derived variables: {len(result.get('derived_variables', []))}")
        print(f"    - Questions updated: {len(result.get('questions_updated', []))}")
    
    credits = final_task.get("credit_usage") or 0
    return result, {"credits": credits}


def _build_resolution_prompt(num_questions: int, num_unmapped: int) -> str:
    """Build the resolution prompt - PASS 2B ORPHAN CLOSURE from master prompt.
    
    Data is provided as file attachments, not embedded in prompt.
    """
    return f'''You are an expert survey programmer + data architect. Your task is PASS 2B: ORPHAN CLOSURE.

=============================================================================
INPUT FILES (ATTACHED)
=============================================================================
1. questions_mapped.json - {num_questions} questions already mapped to variables
2. unmapped_vars.json - {num_unmapped} unmapped variables with their metadata

FIRST: Read both files completely.

=============================================================================
OUTPUT REQUIREMENT  
=============================================================================
You MUST save your output to a file named: resolution_output.json

The file MUST have this EXACT structure:
{{
  "derived_variables": [
    {{
      "var": "<WEIGHT_VAR>",
      "source_vars": ["<VAR1>", "<VAR2>", "<VAR3>"],
      "description": "Survey weight for sample balancing"
    }}
  ],
  "questions_updated": [
    // ALL questions from questions_mapped.json
    // WITH any newly attached vars or new questions added
    // Same structure: id, section, text, type, vars, answers:{{}}, logics:[]
    // PRESERVE: grid_rows, grid_columns, answer_options from input when present
  ]
}}

CRITICAL: You MUST reach ZERO unmapped variables. Every variable must end up in either:
- A question's vars array, OR
- The derived_variables array

=============================================================================
RESOLUTION ORDER (STRICT - FOLLOW EXACTLY)
=============================================================================

For EACH unmapped variable, apply these steps IN ORDER until resolved:

STEP 1: ATTACH TO EXISTING STRUCTURE/GROUP
-----------------------------------------
Check if the variable belongs to an already-mapped question:

A) MISSED MULTI-SELECT OPTION:
   - Does naming pattern match an existing multi-select?
   - Add to that question's vars array

B) MISSED GRID CELL:
   - Does naming pattern match an existing grid?
   - Add as new row or complete existing rows

C) OTHER-SPECIFY TEXT FIELD:
   - Is it *_OTH, *_OTHER, *_SPECIFY, *_TEXT paired with existing question?
   - Add to the parent question's vars OR create linked open_text question

D) LOOP/REPEAT ITERATION:
   - Is it part of a loop block with iteration suffix?
   - Group with related loop questions

→ If matched: UPDATE the question's vars array in questions_updated

STEP 2: MATCH TO SINGLE QUESTION
--------------------------------
Check if this is a completely missed question:

A) LABEL MATCH:
   - Does variable label match any question text from PDF?
   
B) VALUE-LABEL MATCH:
   - Do value labels match answer options from a PDF question?

C) ORDER/ADJACENCY:
   - Is it adjacent to mapped variables that suggest it's a separate question?

→ If matched: CREATE new question entry in questions_updated with:
   - id: infer from variable name or create logical ID
   - section: infer from position
   - text: use variable label or "[Question text not found in PDF]"
   - type: infer from structure (single_select/numeric/open_text/multi_select)
   - vars: [this variable]
   - answers: {{}}
   - logics: []

STEP 3: CLASSIFY AS DERIVED VARIABLE
------------------------------------
For variables that are NOT direct survey responses, classify as derived.

HOW TO DETECT DERIVED VARIABLES:

1) READ THE LABEL - it often tells you directly:
   - Labels containing "Hidden", "Recode", "Net", "Group", "Band" → recodes
   - Labels containing "Timer", "Duration", "Time" → timers
   - Labels containing "Flag", "Status", "Indicator" → flags
   - Labels containing "Weight" → survey weights
   - Labels containing "Quota", "Segment", "Cell" → quota vars
   - Labels containing "Order", "Random" → randomization tracking

2) LOOK AT THE NAME PREFIX/SUFFIX:
   - Single letter prefixes often indicate derived (especially lowercase)
   - Suffixes like _GROUP, _BAND, _NET, _FLAG, _TIMER → derived

3) CHECK IF IT'S A TRANSFORMATION:
   - Does the name reference another variable? (e.g., contains a question ID)
   - Does it aggregate multiple vars? (contains "Net", "Total", "Sum")

DERIVED VARIABLE CLASSIFICATION:

Focus on identifying source_vars accurately. The type/category is less important than getting the source variables correct.

For all derived variables:
   - source_vars: the variable(s) that determine or create this derived variable
   - If system-generated with no clear sources: source_vars: [itself]
   - If purpose unclear: source_vars: [itself], description: "Purpose unclear - requires manual review"

=============================================================================
CRITICAL: INVESTIGATION FOR RECODES THAT IMPACT LOGIC
=============================================================================

For recodes that could impact skip logic (quotas, classifications, segmentations):
These recodes may be used as sources for section gates and routing logic.

INVESTIGATION PROCESS (MANDATORY BEFORE ASSIGNING source_vars):

1. READ THE VARIABLE DESCRIPTION CAREFULLY:
   - Understand what the recode represents
   - Identify what classification or grouping it creates

2. CROSS-REFERENCE WITH QUESTIONS:
   - Cross-reference variable label/description with question text in questions_mapped.json
   - Match variable description to question text and answer options
   - Check variable names and descriptions for clues about which questions they reference
   - Search questions_mapped.json for question text that matches the description

3. IDENTIFY SOURCE QUESTIONS:
   - Identify which questions are referenced in the description
   - If description mentions section gates or routing, check those questions
   - Verify source_vars logically match the derived variable's purpose

4. VERIFY SOURCE_VARS:
   - Verify source_vars match the actual questions referenced in the description
   - Verify source_vars match those questions
   - This verification must happen BEFORE assigning source_vars

CRITICAL: For recodes that could be sources for skip logic:
   - INVESTIGATE DEEPLY: Match variable description to question text and variable names
   - Verify source_vars match the actual questions referenced in the description
   - Don't assign source_vars without verifying they match the variable's purpose

STEP 4: LAST RESORT
-------------------
If you cannot determine the purpose, still add it as derived:
{{
  "var": "<VAR_NAME>",
  "source_vars": ["<VAR_NAME>"],
  "description": "Purpose unclear - requires manual review"
}}

Most unmapped variables should be resolved, but internal/system variables with no impact on logic may be classified as derived with source_vars: [itself] if they don't affect skip logic or question routing.

=============================================================================
OUTPUT FORMAT (STRICT JSON)
=============================================================================

{{
  "derived_variables": [
    {{
      "var": "<RECODE_VAR>",
      "source_vars": ["<SOURCE_VAR>"],
      "description": "<description of the recode transformation>"
    }},
    {{
      "var": "<WEIGHT_VAR>",
      "source_vars": ["<VAR1>", "<VAR2>", "<VAR3>"],
      "description": "Survey weight for sample balancing"
    }},
    {{
      "var": "<FLAG_VAR>",
      "source_vars": ["<FLAG_VAR>"],
      "description": "<description of what the flag indicates>"
    }},
    {{
      "var": "<TIMER_VAR>",
      "source_vars": ["<TIMER_VAR>"],
      "description": "<description of what is being timed>"
    }},
    {{
      "var": "<SYSTEM_VAR>",
      "source_vars": ["<SYSTEM_VAR>"],
      "description": "<description of system metadata>"
    }},
    {{
      "var": "<COMPUTED_VAR>",
      "source_vars": ["<INPUT_VAR>"],
      "description": "<description of the computation/classification>"
    }},
    {{
      "var": "<AGGREGATE_VAR>",
      "source_vars": ["<VAR>_1", "<VAR>_2", "<VAR>_3"],
      "description": "<description of the aggregation>"
    }}
  ],
  "questions_updated": [
    // COMPLETE list of ALL questions
    // Same structure as questions_mapped input
    // WITH any newly attached vars or new questions added
    // Preserve exact order
    // PRESERVE: grid_rows, grid_columns, answer_options from input when present
    // Every question: "answers": {{}}, "logics": []
  ]
}}

=============================================================================
CRITICAL RULES (GATE 3 MUST PASS)
=============================================================================

1) Every unmapped variable should be resolved, but focus on variables that impact skip logic:
   - Variables that could be sources for routing → classify as derived with accurate source_vars
   - Internal/system variables with no logic impact → may be classified as derived with source_vars: [itself]

2) derived_variables[*].source_vars MUST NOT be empty
   - Use [itself] as last resort for system-generated variables

3) derived_variables[*].description MUST be meaningful
   - Explain what it represents and how it's derived

4) Preserve question order EXACTLY from input

5) Every question MUST have "answers": {{}} and "logics": []

6) Do NOT invent variable names - only use names from unmapped_vars.json

7) For recodes that could impact skip logic: verify source_vars match the description
   - Don't assign source_vars without verifying they match the variable's purpose

=============================================================================
VALIDATION BEFORE SAVING (MANDATORY)
=============================================================================

Count your work:
1. Count unmapped_vars from input: N
2. Count vars added to questions: X  
3. Count derived_variables: Y
4. VERIFY: X + Y == N

If the counts don't match, you have lost variables. Review each unmapped var
and ensure it's either attached to a question or in derived_variables.

EVERY SINGLE unmapped variable must be accounted for - no exceptions.

=============================================================================
FINAL STEP - SAVE OUTPUT
=============================================================================

After validation passes, SAVE your result to: resolution_output.json
The file must contain valid JSON with "derived_variables" and "questions_updated" arrays.
'''


def main():
    parser = argparse.ArgumentParser(description="Step 4: Resolve unmapped variables (PASS 2B)")
    parser.add_argument("--mapped", "-m", required=True, help="Path to mapping JSON (from Step 3)")
    parser.add_argument("--inventory", "-i", required=True, help="Path to dataset inventory JSON (from Step 2)")
    parser.add_argument("--output", "-o", default="output/s4_resolution.json", help="Output JSON file")
    parser.add_argument("--quiet", "-q", action="store_true", help="Reduce output")
    args = parser.parse_args()
    
    from dotenv import load_dotenv
    load_dotenv()
    
    print("\n[Step 4] Unmapped Variable Resolution (PASS 2B)")
    print("=" * 50)
    
    with open(args.mapped) as f:
        mapped_data = json.load(f)
    
    with open(args.inventory) as f:
        inv_data = json.load(f)
    inventory = inv_data if isinstance(inv_data, list) else inv_data.get("variables", [])
    
    result, _ = resolve_unmapped_variables(
        mapped_data.get("questions_mapped", []),
        mapped_data.get("unmapped_vars", []),
        inventory,
        show_progress=not args.quiet
    )
    
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)
    
    print(f"\nResult saved to: {args.output}")


if __name__ == "__main__":
    main()
