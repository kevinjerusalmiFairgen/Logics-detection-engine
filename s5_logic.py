#!/usr/bin/env python3
"""
Step 5: Logic Extraction and Routing Expansion (PASS 3)

Adds logic objects to each question using the logic decision tree.
Expands ALL routing instructions per canonical rules.
All logic is atomic at target-question level.

Usage:
    python s5_logic.py --questions s4_result.json --instructions s1_result.json --output s5_result.json
"""

import json
import os
import argparse
from typing import Dict, List

from utils import ManusAPIClient, extract_json_from_task


def extract_logic_and_routing(
    questions_updated: List[Dict],
    logic_instructions: List[Dict],
    derived_variables: List[Dict] = None,
    show_progress: bool = True
) -> List[Dict]:
    """
    Use Manus to extract logic and expand routing (PASS 3).
    Uploads data as files instead of embedding in prompt.
    
    Args:
        questions_updated: Questions with vars mapped
        logic_instructions: Logic instructions from PDF
        derived_variables: Recodes and derived vars (logic may reference these)
        show_progress: Whether to display progress
    
    Returns:
        List of questions with logics array populated
    """
    client = ManusAPIClient()
    derived_variables = derived_variables or []
    
    # Upload with explicit file names
    if show_progress:
        print("  Uploading questions.json...")
    questions_upload = client.upload_json(questions_updated, "questions.json")
    
    if show_progress:
        print("  Uploading logic_instructions.json...")
    logic_upload = client.upload_json(logic_instructions, "logic_instructions.json")
    
    # Upload derived variables (recodes) - logic may reference these
    if show_progress:
        print("  Uploading derived_variables.json...")
    derived_upload = client.upload_json(derived_variables, "derived_variables.json")
    
    prompt = _build_logic_prompt(len(questions_updated), len(logic_instructions), len(derived_variables))
    
    if show_progress:
        print("  Creating logic extraction task...")
    
    task_result = client.create_task(
        prompt=prompt,
        attachments=[
            {"file_id": questions_upload.file_id},
            {"file_id": logic_upload.file_id},
            {"file_id": derived_upload.file_id}
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
        max_wait=1800,
        show_thinking=show_progress
    )
    
    if final_task.get("status") != "completed":
        raise Exception(f"Task failed: {final_task.get('status')}")
    
    result = extract_json_from_task(client, final_task)
    questions_with_logic = result if isinstance(result, list) else result.get("questions", [])
    
    if show_progress:
        total_logics = sum(len(q.get("logics", [])) for q in questions_with_logic)
        print(f"  Logic extraction complete:")
        print(f"    - Questions: {len(questions_with_logic)}")
        print(f"    - Total logic rules: {total_logics}")
    
    return questions_with_logic


def _build_logic_prompt(num_questions: int, num_instructions: int, num_derived: int = 0) -> str:
    """Build the logic extraction prompt - PASS 3 from master prompt.
    
    Data is provided as file attachments, not embedded in prompt.
    """
    return f'''You are an expert survey programmer + "logic detective". Your task is PASS 3: LOGIC EXTRACTION.

Add logic objects to each question. All logic must be atomic at target-question level.
Apply the logic decision tree IN ORDER. Enforce canonical routing expansion.

THREE FILES ARE ATTACHED:
1. questions.json - {num_questions} questions with id, section, text, type, vars, answers, logics
2. logic_instructions.json - {num_instructions} raw logic instructions from PDF
3. derived_variables.json - {num_derived} derived variables (RECODES, FLAGS, WEIGHTS, etc.)

READ ALL THREE FILES before starting.

=============================================================================
IMPORTANT: RECODES AND DERIVED VARIABLES
=============================================================================

The derived_variables.json contains RECODES and computed variables like:
- <VAR>_GROUP (recode from <VAR>)
- <VAR>_BAND (recode from <VAR>)  
- <SEGMENT_VAR> (segment classification)
- FLAG_* (status flags)

LOGIC CONDITIONS MAY REFERENCE THESE RECODES!
If a logic instruction says "If <RECODE_VAR> = 2" or "If segment = X", use the 
actual recode variable name from derived_variables.json in your condition.

Example: If derived_variables has {{"var": "<SEGMENT_VAR>", "source_vars": ["<SRC1>", "<SRC2>"]}}
And logic says "If <segment_condition>, ask Section C"
Then condition should reference <SEGMENT_VAR> (the recode), not the source vars.

NOTE: Recode variables CAN be referenced in OTHER logic conditions!
Example: If <RECODE_VAR> is a recode, skip logic can use "<RECODE_VAR> == 1" as condition.

=============================================================================
LOGIC DECISION TREE (APPLY IN THIS EXACT ORDER)
=============================================================================

For each potential rule, classify using this order:

1) If rule determines whether a question is asked → type = "skip"
2) Else if rule enforces none/DK/RF non-cooccurrence → type = "exclusive"
3) Else if rule enforces min/max/exactly number selected → type = "count"
4) Else if rule enforces arithmetic total/add-up → type = "sum"
5) Else if rule filters/carries forward downstream answer options → type = "piping"
6) Else if rule is deterministic derived transformation → type = "recode"
7) Else → type = "custom"

=============================================================================
LOGIC DEFINITIONS (SINGLE SOURCE OF TRUTH)
=============================================================================

A) skip / section_skip
----------------------
- MEANING: Current target question is NOT asked when condition is TRUE.
- Use "section_skip" when the skip originates from a section gate; use "skip" for question-level routing.
- Simplify logically equivalent conditions into one rule.
- PLACEMENT: ONLY on target question(s) being skipped. NEVER on source question.
- CONDITION SEMANTICS: TRUE => skip this question (do not ask it)
- source_vars: Gating variable(s) referenced in the condition
- target_vars: MUST EQUAL current question's vars (this is mandatory!)
- FOR ASK-IF RULES: Invert the ask-if condition into a skip condition

LOGIC GROUPING (CRITICAL):
- If ONE instruction groups conditions together (e.g., "skip Q3 if Q1=1 AND Q2=2"), create ONE logic entry:
  * condition: "Q1 = 1 AND Q2 = 2" (compound)
  * source_vars: [Q1, Q2] (all sources)
  * ONE logic object total
- If instructions are SEPARATE (e.g., "skip Q3 if Q1=1" and separately "skip Q3 if Q2=2"), create SEPARATE logic entries:
  * Logic 1: condition "Q1 = 1", source_vars: [Q1]
  * Logic 2: condition "Q2 = 2", source_vars: [Q2]
  * TWO logic objects total
- DO NOT ungroup compound conditions - preserve how conditions are grouped in the original instruction

B) exclusive
------------
- MEANING: Exclusive option(s) cannot co-occur with non-exclusive options in same multi-select.
- PLACEMENT: On the multi-select question itself.
- ONLY for multi_select questions. Single-select is inherently exclusive - no logic needed.
- APPLIES TO: Multi-select questions with "None of the above", "Don't know", "Refuse", etc.
- source_vars: FULL option set for that question (all multi-select vars)
- target_vars: ONLY the exclusive anchor var(s) - typically *_97, *_98, *_99 or similar
- DETECTION: Look for variables ending in _97/_98/_99, or instructions mentioning 
  "none", "don't know", "refuse", "cannot be selected with", "mutually exclusive"

C) count
--------
- MEANING: Min/max/exactly constraints on number of options selected.
- PLACEMENT: On the question with the constraint.
- source_vars: Variables being counted (the multi-select options)
- target_vars: Current question's vars
- DETECTION: "select exactly N", "select at least N", "select at most N", 
  "select up to N", "minimum N", "maximum N", "choose N"
- CRITICAL: This is the ONLY type allowed for min/max/exactly constraints.
  NEVER use "min_max" - that token is forbidden.

D) sum
------
- MEANING: Sum/add-up constraints (values must total to a specific amount).
- PLACEMENT: On the question with the constraint.
- source_vars: Variables in the sum (+ total var if explicitly referenced)
- target_vars: Same as source_vars (the variables being summed)
- DETECTION: "must add up to", "total must equal", "sum to 100%", "allocate 100 points"

E) piping
---------
- MEANING: Answer-option filtering/carry-forward/elimination in downstream question.
- PLACEMENT: On the DOWNSTREAM filtered question (not the source question).
- source_vars: UPSTREAM selector variable(s) that control the filtering
- target_vars: DOWNSTREAM answer option vars that get filtered
- PIPING IS ANSWER-OPTION FILTERING ONLY. Text piping (inserting values into question wording) is NOT logic.
- DETECTION: "show only items selected in <source>", "carry forward", "based on selections"
- NOTE: In most funnels, source_vars and target_vars are same-size aligned lists (1:1).
  Non-1:1 allowed if condition is still boolean and valid.

F) recode
---------
- MEANING: Deterministic derived-variable transformation.
- PLACEMENT: Associated with the derived variable.
- source_vars: Input variable(s) used in the derivation
- target_vars: The derived variable(s) being assigned/used
- REQUIREMENT: The derived variable MUST exist in derived_variables.json
- NOTE: See "IMPORTANT: RECODES AND DERIVED VARIABLES" section above for how recodes can be referenced in other logic conditions

G) custom
---------
- MEANING: Valid rule not representable by the other six types.
- PLACEMENT: On the affected question.
- source_vars: All variables referenced in the rule
- target_vars: Affected vars for the current question
- USE FOR: Complex conditional logic, formulas, validations that don't fit above

=============================================================================
CRITICAL: IGNORE ALL TERMINATE/SCREENOUT CONDITIONS
=============================================================================

The dataset ONLY contains completed responses. All termination/screenout conditions
have ALREADY been applied during data collection. Therefore:

- DO NOT expand "terminate", "screen out", "end survey", "skip to end" conditions
- DO NOT create skip logic from terminate conditions
- COMPLETELY IGNORE any logic instruction with target_question = "END"
- COMPLETELY IGNORE any instruction containing "terminate", "screen out", "end survey"

These conditions do NOT need skip logic because the dataset is already filtered.
Only expand ACTUAL routing between questions/sections.

HOW TO HANDLE TERMINATE INSTRUCTIONS:
- SKIP this instruction entirely
- DO NOT create any skip logic from terminate conditions
- Move on to the next logic instruction
- Result: IGNORE - do not create any skip logic from terminate conditions

=============================================================================
COMPLEX/SECTION-LEVEL LOGIC: CHECK RECODES FIRST
=============================================================================

For complex or repeated logic conditions (especially section-level routing),
check derived_variables.json for a recode that captures the same classification.

MANDATORY RECODE CHECK FOR SECTION GATES:
- Before creating compound conditions for section gates:
  1. Check derived_variables.json for any recode matching the section gate concept
  2. If recode exists and matches, USE THE RECODE (it simplifies the logic)
  3. If no recode matches, use compound raw variables
- This check is MANDATORY, not optional
- This check must happen BEFORE creating any compound conditions

WHEN TO USE A RECODE:
- The recode's description clearly matches the condition concept
- The recode's source_vars include the question(s) referenced in the instruction
- The recode represents the same classification/logic as the section gate

PREFERENCE RULE: If a recode exists and matches the concept, USE IT - recodes simplify 
complex compound conditions into single variable references. Only use raw compound 
conditions if no matching recode exists.

IF RECODE MATCHES → Use the recode variable in source_vars (preferred - simpler)

IF NO RECODE MATCHES → Use compound raw variables (fallback only)

For section gates and repeated conditions, INVESTIGATE before deciding source_vars:
1. Check derived_variables.json for any recode that matches the concept
2. Verify the source is complete (not missing any part of the condition)
3. Document your reasoning in condition field

=============================================================================
ROUTING EXPANSION (CANONICAL - MANDATORY)
=============================================================================

Use questionnaire order from the questions array. Expand routing instructions
into individual skip logic entries on the affected questions.

CORE PRINCIPLE: Skip logic is ALWAYS placed on the question(s) being SKIPPED,
never on the source question that triggers the skip.

-----------------------------------------------------------------------------
1) SKIP TO QUESTION X
-----------------------------------------------------------------------------
Trigger phrases: "skip to <Q>", "go to <Q>", "jump to <Q>", "continue at <Q>"

WHAT IT MEANS: Jump forward to question X, skipping all questions in between.

HOW TO EXPAND:
- Find all questions BETWEEN source and target (exclusive of both)
- Add skip logic to EACH of those intermediate questions
- Do NOT add skip to the source question
- Do NOT add skip to the target question X (that one gets asked)

EXAMPLE:
  Instruction: "If <QA>=2, skip to <QE>"
  Questions in order: QA, QB, QC, QD, QE
  
  Result: Add skip to QB, QC, QD (the questions being jumped over)
  - QB: {{"type": "skip", "condition": {{"var": "<QA_VAR>", "op": "eq", "value": 2}}, "source_vars": ["<QA_VAR>"], "target_vars": [QB's vars]}}
  - QC: {{"type": "skip", "condition": {{"var": "<QA_VAR>", "op": "eq", "value": 2}}, "source_vars": ["<QA_VAR>"], "target_vars": [QC's vars]}}
  - QD: {{"type": "skip", "condition": {{"var": "<QA_VAR>", "op": "eq", "value": 2}}, "source_vars": ["<QA_VAR>"], "target_vars": [QD's vars]}}

-----------------------------------------------------------------------------
2) SKIP TO SECTION S
-----------------------------------------------------------------------------
Trigger phrases: "skip to Section B", "go to Section C", "continue at Section D"

WHAT IT MEANS: Jump forward to the START of section S, skipping everything in between.

HOW TO EXPAND:
- Find the FIRST question of Section S
- Find all questions BETWEEN source and that first question (exclusive)
- Add skip logic to each intermediate question

EXAMPLE:
  Instruction: "If <condition>, skip to Section C"
  Section A: QA1, QA2, QA3  |  Section B: QB1, QB2, QB3  |  Section C: QC1, QC2
  Source is QA3 (last in Section A)
  
  Result: Add skip to QB1, QB2, QB3 (all of Section B)
  - QB1, QB2, QB3 each get: {{"type": "skip", "condition": {{"var": "<SOURCE_VAR>", "op": "<op>", "value": <val>}}, ...}}

-----------------------------------------------------------------------------
3) SKIP SECTION S (Skip an entire section)
-----------------------------------------------------------------------------
Trigger phrases: "skip Section B", "do not ask Section B", "Section B not applicable"

WHAT IT MEANS: Skip ALL questions within that section.

HOW TO EXPAND:
- Find ALL questions that belong to Section S
- Add skip logic to EVERY question in that section

EXAMPLE:
  Instruction: "If <condition>, skip Section B"
  Section B contains: QB1, QB2, QB3, QB4
  
  Result: Add skip to QB1, QB2, QB3, QB4 (every question in Section B)

-----------------------------------------------------------------------------
4) SECTION ELIGIBILITY GATE (Ask section if...)
-----------------------------------------------------------------------------
Trigger phrases: "Section X: Ask if <condition>", "Ask Section Y only if <condition>"

WHAT IT MEANS: The ENTIRE section is conditional. Invert to skip condition.

HOW TO EXPAND:
- Find ALL questions in that section
- INVERT the eligibility condition into a skip condition
- Add skip logic to EVERY question in that section

VERIFICATION REQUIREMENT (MANDATORY):
- After expanding a section gate, verify:
  * Count: How many questions are in this section?
  * Count: How many questions have section_skip logic?
  * If counts don't match, you missed questions - find them and add section_skip logic
- This verification must happen BEFORE saving output

EXAMPLE:
  Instruction: "Section B: Ask only if <eligibility_condition>"
  Section B contains: QB1, QB2, QB3
  
  Inverted skip condition: NOT(<eligibility_condition>)
  Result: Add skip to QB1, QB2, QB3
  - Each gets: {{"type": "skip", "condition": {{"var": "<SOURCE_VAR>", "op": "<inverted_op>", "value": <val>}}, ...}}

-----------------------------------------------------------------------------
5) ASK QUESTION IF (Single question condition)
-----------------------------------------------------------------------------
Trigger phrases: "Ask <Q> if...", "<Q>: Show if...", "Display <Q> only if..."

WHAT IT MEANS: Single question is conditional. Invert to skip condition.

HOW TO EXPAND:
- INVERT the ask-if condition into a skip condition
- Add skip logic to that ONE question only

-----------------------------------------------------------------------------
6) GO TO END / TERMINATE (Screen-out routing) - **IGNORE COMPLETELY**
-----------------------------------------------------------------------------
Trigger phrases: "skip to end", "terminate", "end survey", "screen out"

**DO NOT EXPAND THESE!** The dataset only contains completed responses.
Terminate conditions have already been applied during data collection.

HOW TO HANDLE:
- SKIP this instruction entirely
- DO NOT create any skip logic from terminate conditions
- Move on to the next logic instruction

Result: IGNORE - do not create any skip logic from terminate conditions.

(Refer to "CRITICAL: IGNORE ALL TERMINATE/SCREENOUT CONDITIONS" section above for full details)
  
=============================================================================
ROUTING EXPANSION VALIDATION
=============================================================================

After expansion, verify:
- Every routing instruction (EXCEPT terminates) has been expanded into skip logic entries
- Skip logic is on the SKIPPED questions, not on source questions
- For each skip logic, target_vars matches the question's own vars
- Skip-to-question: count of skip entries = count of intermediate questions
- Skip-to-section: all questions between source and section start have skip
- Section gates: COUNT questions in section, COUNT questions with section_skip - MUST MATCH
  * If section gate count doesn't match, you missed questions - fix it
  * This verification is MANDATORY (see section gate expansion above)
- Terminate/screenout conditions: IGNORED (no skip logic created)

=============================================================================
CRITICAL: USE DATA VARIABLE NAMES (NOT QUESTION IDs)
=============================================================================

ALL logic must reference ACTUAL DATA VARIABLES from the question's "vars" array.
NEVER use questionnaire IDs in logic - use the mapped variable names from the vars array.

CORRECT (using data variables):
  "condition": {{"var": "<ACTUAL_VAR_NAME>", "op": "eq", "value": 2}}
  "source_vars": ["<ACTUAL_VAR_NAME>"]

HOW TO TRANSLATE:
- PDF says "If QA = 2, skip to QC"
- Look up QA's vars array → ["<VAR_A>"]  
- Look up QC's vars array → ["<VAR_C>"]
- Result: condition references <VAR_A>, source_vars = ["<VAR_A>"], target_vars = ["<VAR_C>"]

The questions.json input file already has "vars" mapped for each question.
Use those variable names in ALL logic conditions, source_vars, and target_vars.

=============================================================================
OUTPUT FORMAT (JSON ARRAY)
=============================================================================

[
  {{
    "id": "<question_id>",
    "section": "<section_id>",
    "text": "<question text>",
    "type": "single_select",
    "vars": ["<VAR_NAME>"],
    "answers": {{}},
    "logics": []
  }},
  {{
    "id": "<question_id>",
    "section": "<section_id>",
    "text": "<question text>",
    "type": "numeric",
    "vars": ["<VAR_NAME>"],
    "answers": {{}},
    "logics": [
      {{
        "type": "skip",
        "condition": "<SOURCE_VAR> == <value>",
        "source_vars": ["<SOURCE_VAR>"],
        "target_vars": ["<TARGET_VAR>"]
      }}
    ]
  }},
  {{
    "id": "<question_id>",
    "section": "<section_id>",
    "text": "<multi-select question text>",
    "type": "multi_select",
    "vars": ["<VAR>_1", "<VAR>_2", "<VAR>_3", "<VAR>_97"],
    "answers": {{}},
    "logics": [
      {{
        "type": "exclusive",
        "condition": "<VAR>_97 == 1",
        "source_vars": ["<VAR>_1", "<VAR>_2", "<VAR>_3", "<VAR>_97"],
        "target_vars": ["<VAR>_97"]
      }},
      {{
        "type": "count",
        "condition": "count(selected) >= 1 AND count(selected) <= 3",
        "source_vars": ["<VAR>_1", "<VAR>_2", "<VAR>_3", "<VAR>_97"],
        "target_vars": ["<VAR>_1", "<VAR>_2", "<VAR>_3", "<VAR>_97"]
      }}
    ]
  }},
  {{
    "id": "<question_id>",
    "section": "<section_id>",
    "text": "<grid question text>",
    "type": "grid",
    "vars": [["<VAR>_r1_c1", "<VAR>_r1_c2"], ["<VAR>_r2_c1", "<VAR>_r2_c2"]],
    "answers": {{}},
    "logics": [
      {{
        "type": "skip",
        "condition": "<SOURCE_VAR> < <value>",
        "source_vars": ["<SOURCE_VAR>"],
        "target_vars": ["<VAR>_r1_c1", "<VAR>_r1_c2", "<VAR>_r2_c1", "<VAR>_r2_c2"]
      }}
    ]
  }}
]

=============================================================================
CRITICAL RULES (GATE 4 MUST PASS)
=============================================================================

1) Every logic object MUST have exactly: type, condition, source_vars, target_vars
2) source_vars and target_vars MUST NOT be empty (never [])
3) For skip logic: target_vars MUST EQUAL current question's vars ONLY (not other questions' vars!)
4) For grids: FLATTEN vars to single list for target_vars
5) NEVER use "min_max" anywhere - use "count" type for min/max/exactly
6) NO termination/screenout logic - IGNORE all terminate conditions entirely (dataset is clean)
7) Preserve question order EXACTLY
8) Every question MUST have "answers": {{}}
9) Logic types allowed ONLY: skip, section_skip, exclusive, count, sum, piping, recode, custom
10) NEVER bundle multiple questions' vars into one skip rule - each question gets its OWN skip with its OWN vars

=============================================================================
FINAL STEP - SAVE OUTPUT
=============================================================================

After adding logic to all questions, perform final verification:

1. VERIFY SECTION GATES:
   - For each section with a gate, verify all questions in that section have section_skip logic
   - Count questions in section vs. questions with section_skip logic - MUST MATCH
   - If any section gate is incomplete, fix it before saving

2. VERIFY ROUTING EXPANSION:
   - All routing instructions (except terminates) have been expanded
   - Skip logic is on skipped questions, not source questions
   - Target_vars match each question's own vars

3. SAVE OUTPUT:
   - Only save after all section gates are verified complete
   - SAVE your result to: logic_output.json
   - The file must be a valid JSON ARRAY of all questions with their logics populated
'''


def main():
    parser = argparse.ArgumentParser(description="Step 5: Extract logic and expand routing (PASS 3)")
    parser.add_argument("--questions", "-q", required=True, help="Path to questions JSON (from Step 4)")
    parser.add_argument("--instructions", "-i", required=True, help="Path to PDF structure JSON (from Step 1)")
    parser.add_argument("--output", "-o", default="output/s5_logic.json", help="Output JSON file")
    parser.add_argument("--quiet", action="store_true", help="Reduce output")
    args = parser.parse_args()
    
    from dotenv import load_dotenv
    load_dotenv()
    
    print("\n[Step 5] Logic Extraction and Routing Expansion (PASS 3)")
    print("=" * 50)
    
    with open(args.questions) as f:
        q_data = json.load(f)
    questions = q_data.get("questions_updated", q_data.get("questions", []))
    
    with open(args.instructions) as f:
        struct = json.load(f)
    logic_instructions = struct.get("logic_instructions", [])
    
    result = extract_logic_and_routing(questions, logic_instructions, show_progress=not args.quiet)
    
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump({"questions": result}, f, indent=2)
    
    print(f"\nResult saved to: {args.output}")


if __name__ == "__main__":
    main()
