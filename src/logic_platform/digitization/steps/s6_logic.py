#!/usr/bin/env python3
"""
Step 6: Logic Extraction and Routing Expansion (PASS 3)

Adds logic objects to each question using the logic decision tree.
Expands ALL routing instructions per canonical rules.
All logic is atomic at target-question level.
Uses pattern_report from Step 5 for exclusive logic (no hardcoded conventions).

Usage:
    python s6_logic.py --questions s4_result.json --instructions s1_result.json --pattern-report pattern_report.json --output s6_result.json
"""

import json
import os
import argparse
from typing import Dict, List

from logic_platform.utils import ManusAPIClient, extract_json_from_task, flatten_vars
from logic_platform.opus_utils import call_opus_json, estimate_opus_cost


def extract_logic_and_routing(
    questions_updated: List[Dict],
    logic_instructions: List[Dict],
    derived_variables: List[Dict] = None,
    pattern_report: Dict = None,
    show_progress: bool = True,
    engine: str = "manus",
) -> tuple:
    """
    Extract logic and expand routing (PASS 3).
    
    Returns:
        (questions_with_logic, cost_info) - cost_info is {"credits": N} or {"input_tokens": N, "output_tokens": N}
    """
    derived_variables = derived_variables or []
    pattern_report = pattern_report or {}
    if engine == "opus":
        return _logic_with_opus(questions_updated, logic_instructions, derived_variables, pattern_report, show_progress)
    return _logic_with_manus(questions_updated, logic_instructions, derived_variables, pattern_report, show_progress)


def _logic_with_opus(
    questions_updated: List[Dict],
    logic_instructions: List[Dict],
    derived_variables: List[Dict],
    pattern_report: Dict,
    show_progress: bool,
) -> tuple:
    """Use Claude Opus 4.6 on Vertex AI."""
    prompt = _build_logic_prompt(
        len(questions_updated), len(logic_instructions), len(derived_variables),
        bool(pattern_report),
    )
    prompt = prompt.replace("FILES ARE ATTACHED:", "INPUT DATA (provided below as JSON):")
    prompt = prompt.replace(
        "7. SAVE OUTPUT:\n   - Only save after ALL verifications pass\n   - SAVE your result to: logic_output.json\n   - The file must be a valid JSON ARRAY of all questions with their logics populated",
        "7. OUTPUT: Respond with ONLY a valid JSON object. No markdown, no code blocks.\n   Use key \"questions\" with an array of all questions with their logics populated."
    )
    json_blocks = {
        "questions.json": questions_updated,
        "logic_instructions.json": logic_instructions,
        "derived_variables.json": derived_variables,
    }
    if pattern_report:
        json_blocks["pattern_report.json"] = pattern_report
    result, usage = call_opus_json(prompt, json_blocks, show_progress=show_progress)
    questions_with_logic = result if isinstance(result, list) else result.get("questions", [])
    questions_with_logic = _apply_pattern_report_exclusives(questions_with_logic, pattern_report)
    if show_progress:
        total_logics = sum(len(q.get("logics", [])) for q in questions_with_logic)
        print(f"  Logic extraction complete:")
        print(f"    - Questions: {len(questions_with_logic)}")
        print(f"    - Total logic rules: {total_logics}")
        print(f"    - Tokens: {usage['input_tokens']} in, {usage['output_tokens']} out (~${estimate_opus_cost(usage['input_tokens'], usage['output_tokens']):.4f})")
    return questions_with_logic, usage


def _logic_with_manus(
    questions_updated: List[Dict],
    logic_instructions: List[Dict],
    derived_variables: List[Dict],
    pattern_report: Dict,
    show_progress: bool,
) -> tuple:
    """Use Manus to extract logic and expand routing (PASS 3)."""
    client = ManusAPIClient()
    derived_variables = derived_variables or []
    pattern_report = pattern_report or {}
    
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
    
    attachments = [
        {"file_id": questions_upload.file_id},
        {"file_id": logic_upload.file_id},
        {"file_id": derived_upload.file_id}
    ]
    if pattern_report:
        if show_progress:
            print("  Uploading pattern_report.json...")
        pattern_upload = client.upload_json(pattern_report, "pattern_report.json")
        attachments.append({"file_id": pattern_upload.file_id})
    
    prompt = _build_logic_prompt(
        len(questions_updated), len(logic_instructions), len(derived_variables),
        bool(pattern_report)
    )
    
    if show_progress:
        print("  Creating logic extraction task...")
    
    task_result = client.create_task(
        prompt=prompt,
        attachments=attachments,
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
    questions_with_logic = result if isinstance(result, list) else result.get("questions", [])
    
    # Apply pattern_report exclusive anchors (data-driven, no hardcoded conventions)
    questions_with_logic = _apply_pattern_report_exclusives(
        questions_with_logic, pattern_report
    )
    
    if show_progress:
        total_logics = sum(len(q.get("logics", [])) for q in questions_with_logic)
        print(f"  Logic extraction complete:")
        print(f"    - Questions: {len(questions_with_logic)}")
        print(f"    - Total logic rules: {total_logics}")
    
    credits = final_task.get("credit_usage") or 0
    return questions_with_logic, {"credits": credits}


def _apply_pattern_report_exclusives(
    questions: List[Dict], pattern_report: Dict
) -> List[Dict]:
    """
    Add exclusive logic using pattern_report.exclusive_anchors (data-driven).
    For each entry: if question lacks exclusive logic, add it using reported vars.
    No hardcoded code conventions.
    """
    anchors = pattern_report.get("exclusive_anchors", [])
    if not anchors:
        return questions
    
    q_by_id = {q.get("id"): q for q in questions if q.get("id")}
    out = []
    for q in questions:
        q = dict(q)
        qid = q.get("id")
        entry = next((a for a in anchors if a.get("question_id") == qid), None)
        if not entry:
            out.append(q)
            continue
        
        anchor_vars = entry.get("vars") or []
        if not anchor_vars:
            out.append(q)
            continue
        
        has_exclusive_logic = any(l.get("type") == "exclusive" for l in q.get("logics", []))
        if has_exclusive_logic:
            out.append(q)
            continue
        
        vars_list = flatten_vars(q.get("vars", []))
        if not vars_list:
            out.append(q)
            continue
        
        logics = list(q.get("logics", []))
        cond_parts = [f"{a} == 1" for a in anchor_vars]
        condition = " OR ".join(cond_parts) if len(cond_parts) > 1 else cond_parts[0]
        logics.append({
            "type": "exclusive",
            "condition": f"Exclusive option selected ({condition}) prevents co-selection",
            "source_vars": vars_list,
            "target_vars": anchor_vars,
        })
        q["logics"] = logics
        out.append(q)
    return out


def _build_logic_prompt(
    num_questions: int, num_instructions: int, num_derived: int = 0,
    has_pattern_report: bool = False
) -> str:
    """Build the logic extraction prompt - PASS 3 from master prompt.
    
    Data is provided as file attachments, not embedded in prompt.
    """
    files_desc = f'''1. questions.json - {num_questions} questions with id, section, text, type, vars, answers, logics
2. logic_instructions.json - {num_instructions} raw logic instructions from PDF
3. derived_variables.json - {num_derived} derived variables (RECODES, FLAGS, WEIGHTS, etc.)'''
    if has_pattern_report:
        files_desc += '''
4. pattern_report.json - exclusive_anchors, recode_patterns, multiselect_groups (from Step 5)
   USE THIS for exclusives: do NOT re-discover. Apply exclusive_anchors per question.
   Verify recodes against recode_patterns. Use multiselect_groups for piping context.'''
    files_desc += "\n\nREAD ALL ATTACHED FILES before starting."
    
    return f'''You are an expert survey programmer + "logic detective". Your task is PASS 3: LOGIC EXTRACTION.

Add logic objects to each question. All logic must be atomic at target-question level.
Apply the logic decision tree IN ORDER. Enforce canonical routing expansion.

FILES ARE ATTACHED:
{files_desc}

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
MANDATORY LOGIC REASONING FRAMEWORK (APPLY TO EVERY INSTRUCTION)
=============================================================================

Before processing ANY logic instruction, follow this systematic reasoning process:

STEP 1: UNDERSTAND THE INSTRUCTION
- Read the instruction type (ask_if, skip_to, exclusive, etc.)
- Identify the target question(s) or section(s)
- Extract the raw condition or constraint text
- Note any question IDs referenced in the condition

STEP 2: TRANSLATE QUESTION IDs TO VARIABLE NAMES (MANDATORY FIRST STEP)
- Scan the condition for question IDs (any identifier: "Q67_NUM", "QA", "Q1_SELECT", "QX", section codes like "A01", etc.)
- For EACH question ID found:
  * MANDATORY: Look up the question ID in questions.json (NEVER assume question ID equals variable name)
  * If found: Get its "vars" array
  * If not found: Check derived_variables.json (might be a recode)
  * ALWAYS replace the question ID with the actual variable name(s) from vars array
  * CRITICAL RULE: NEVER use question IDs directly in conditions or source_vars - ALWAYS look up vars array first
  * CRITICAL RULE: Even if question ID looks identical to a variable name, you MUST still look it up in questions.json and use the value from vars array
  * If multiple vars exist, determine which one(s) apply based on condition context
- Verify: Re-scan translated condition - no question IDs should remain (only vars array values)
- If any question ID cannot be translated: Investigate before proceeding
- MANDATORY: source_vars MUST contain values from the vars array, never question IDs directly
- MANDATORY: Condition strings MUST contain vars array values, never question IDs

STEP 3: CLASSIFY LOGIC TYPE (DECISION TREE)
Apply this order to determine the logic type:

1) If rule determines whether a question is asked → type = "skip"
2) Else if rule enforces none/DK/RF non-cooccurrence → type = "exclusive"
3) Else if rule enforces min/max/exactly number selected → type = "count"
4) Else if rule enforces arithmetic total/add-up → type = "sum"
5) Else if rule filters/carries forward downstream answer options → type = "piping"
6) Else if rule is deterministic derived transformation → type = "recode"
7) Else → type = "custom"

STEP 4: PROCESS CONDITION (TYPE-SPECIFIC)
- For skip logic: Invert ask_if conditions, expand routing, apply section gates
- For exclusive: Identify exclusive anchor variables
- For count: Extract min/max/exactly constraints
- For sum: Identify variables in the sum
- For piping: Map source to target variables
- For recode: Verify derived variable exists

STEP 5: EXTRACT VARIABLES
- Identify ALL variables referenced in the condition (source_vars)
- Identify ALL variables affected by the logic (target_vars)
- Verify: All variables exist in questions.json vars or derived_variables.json

STEP 6: VERIFY COMPLETENESS
- Check: Is this instruction fully processed?
- Check: Are all question IDs translated?
- Check: Are all variables valid?
- Check: Does the logic type match the instruction semantics?
- If any check fails, investigate and correct before proceeding

STEP 7: CREATE LOGIC ENTRY
- Only after all above steps are complete
- Ensure condition uses variable names (not question IDs)
- Ensure source_vars and target_vars are non-empty
- Ensure logic type is correct

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
- target_vars: ONLY the exclusive anchor var(s) - use pattern_report.exclusive_anchors when available
- DETECTION: Survey-specific codes vary (e.g. _97/_98/_99, _997/_998/_999, r99, etc.).
  Look for instructions mentioning "none", "don't know", "refuse", "cannot be selected with", "mutually exclusive".
  PREFER pattern_report.exclusive_anchors over inferring from variable names.

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
COMPLEX/SECTION-LEVEL LOGIC: RECODE USAGE
=============================================================================

RULE: Always consider the possible source variables. If multiple, check if a
recode unifies them—using it can clarify and simplify the logic.

- Single source (one var, one answer): use the RAW variable directly.
  Example: "if <selector_var> not selected" → condition uses the selector var, not a recode.

- Multiple sources (section gate, compound condition): check derived_variables.json
  for a recode that unifies those sources. If a recode exists and its source_vars
  cover the condition (e.g. a segment recode from multiple eligibility questions),
  USE the recode—it clarifies the logic.

- If no recode unifies the sources, or the recode doesn't match, use raw compound
  variables.

For section gates: list the sources in the condition. If a recode combines them
and represents the gate concept, prefer the recode.

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

MANDATORY PROCESS (FOLLOW EXACTLY):
1. TRANSLATE FIRST: Extract condition, identify all question IDs, look up EACH in questions.json, get its vars array, replace question ID with the variable name(s) from vars
   - CRITICAL: Even if question ID matches a variable name, you MUST look it up and use vars array value
   - Example: Condition says "QX = 1" → Look up QX in questions.json → vars = ['qx_var'] → Use 'qx_var' from vars array (never assume)
2. VERIFY TRANSLATION: Ensure no question IDs remain in condition - all must be replaced with vars array values
3. UNDERSTAND SEMANTICS: "Ask if condition TRUE" = "Show if TRUE" = "Skip if FALSE"
4. INVERT CONDITION: Apply logical inversion (NOT the condition)
   - Simple: "var = value" → "var != value"
   - Compound AND: "A AND B" → "(NOT A) OR (NOT B)"
   - Compound OR: "A OR B" → "(NOT A) AND (NOT B)"
   - Ranges: "var >= 1 AND var <= 49" → "var < 1 OR var > 49"
5. EXTRACT SOURCE VARS: All variables referenced in the inverted condition - MUST be from vars arrays, not question IDs
6. CREATE SKIP LOGIC: Add skip logic to the target question with translated, inverted condition

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
CRITICAL: USE DATA VARIABLE NAMES (NOT QUESTION IDs) - MANDATORY TRANSLATION
=============================================================================

ALL logic must reference ACTUAL DATA VARIABLES from the question's "vars" array.
NEVER use questionnaire IDs in logic - use the mapped variable names from the vars array.

TRANSLATION IS MANDATORY AND MUST HAPPEN FIRST (see Framework Step 2 above):
Before processing any condition, you MUST translate all question IDs to variable names.
This translation happens BEFORE inversion, expansion, or any other processing.

REFERENCE: The detailed translation process is defined in Framework Step 2 above.
Apply that process to ALL condition types: ask_if, skip_to, section gates, exclusive, count, sum, piping, and all other logic types.

VERIFICATION CHECKPOINT:
Before creating ANY logic entry, verify:
- Condition contains NO question IDs (only variable names)
- All variables referenced exist in questions.json vars or derived_variables.json
- source_vars list contains actual variable names from vars arrays (not question IDs)
- CRITICAL: Even if a question ID looks like a variable name, you MUST have looked it up in questions.json and used its vars array value

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
    "vars": ["<VAR>_1", "<VAR>_2", "<VAR>_3", "<EXCLUSIVE_ANCHOR>"],
    "answers": {{}},
    "logics": [
      {{
        "type": "exclusive",
        "condition": "<EXCLUSIVE_ANCHOR> == 1",
        "source_vars": ["<VAR>_1", "<VAR>_2", "<VAR>_3", "<EXCLUSIVE_ANCHOR>"],
        "target_vars": ["<EXCLUSIVE_ANCHOR>"]
      }},
      {{
        "type": "count",
        "condition": "count(selected) >= 1 AND count(selected) <= 3",
        "source_vars": ["<VAR>_1", "<VAR>_2", "<VAR>_3", "<EXCLUSIVE_ANCHOR>"],
        "target_vars": ["<VAR>_1", "<VAR>_2", "<VAR>_3", "<EXCLUSIVE_ANCHOR>"]
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
FINAL VERIFICATION (MANDATORY BEFORE SAVING)
=============================================================================

After processing ALL logic instructions, perform systematic verification:

1. VERIFY TRANSLATION COMPLETENESS (CRITICAL - DO NOT SKIP):
   - Scan ALL logic conditions in ALL questions
   - Verify: NO question IDs remain (only variable names from vars arrays)
   - MANDATORY CHECK: For every variable in conditions and source_vars, verify it came from a vars array lookup
   - REJECT any logic entry that uses question IDs directly in conditions - it must be fixed
   - If any question IDs found: Translate them NOW by looking up vars arrays and update the logic

2. VERIFY VARIABLE VALIDITY:
   - For each logic entry, verify all source_vars exist in:
     * questions.json vars arrays, OR
     * derived_variables.json
   - If any variable not found: Investigate and correct

3. VERIFY SECTION GATES:
   - For each section with a gate, verify all questions in that section have section_skip logic
   - Count questions in section vs. questions with section_skip logic - MUST MATCH
   - If any section gate is incomplete, fix it before saving

4. VERIFY ROUTING EXPANSION:
   - All routing instructions (except terminates) have been expanded
   - Skip logic is on skipped questions, not source questions
   - Target_vars match each question's own vars

5. VERIFY LOGIC TYPE ACCURACY:
   - Each logic type matches its instruction semantics
   - No ask_if instructions left unprocessed
   - No skip_to instructions left unexpanded

6. VERIFY COMPLETENESS:
   - Count logic instructions processed vs. logic entries created
   - Ensure every non-terminate instruction resulted in logic entries
   - If counts don't match: Find missing logic and add it

7. SAVE OUTPUT:
   - Only save after ALL verifications pass
   - SAVE your result to: logic_output.json
   - The file must be a valid JSON ARRAY of all questions with their logics populated
'''


def main():
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Step 6: Extract logic and expand routing (PASS 3)")
    parser.add_argument("--questions", "-q", required=True, help="Path to questions JSON (from Step 4)")
    parser.add_argument("--instructions", "-i", required=True, help="Path to PDF structure JSON (from Step 1)")
    parser.add_argument("--pattern-report", "-p", help="Path to pattern_report.json (from Step 5)")
    parser.add_argument("--derived", help="Path to derived variables (from Step 4 output)")
    parser.add_argument("--output", "-o", default="output/s6_logic.json", help="Output JSON file")
    parser.add_argument("--engine", "-e", choices=["opus", "manus"], default="manus")
    parser.add_argument("--quiet", action="store_true", help="Reduce output")
    args = parser.parse_args()
    
    from dotenv import load_dotenv
    load_dotenv()
    
    print("\n[Step 6] Logic Extraction and Routing Expansion (PASS 3)")
    print("=" * 50)
    
    with open(args.questions) as f:
        q_data = json.load(f)
    questions = q_data.get("questions_updated", q_data.get("questions", []))
    derived = q_data.get("derived_variables", [])
    
    with open(args.instructions) as f:
        struct = json.load(f)
    logic_instructions = struct.get("logic_instructions", [])
    
    if args.derived and os.path.exists(args.derived):
        with open(args.derived) as f:
            d_data = json.load(f)
        derived = d_data.get("derived_variables", derived)
    
    pattern_report = {}
    if args.pattern_report and os.path.exists(args.pattern_report):
        with open(args.pattern_report) as f:
            pattern_report = json.load(f)
    
    result, credits = extract_logic_and_routing(
        questions, logic_instructions,
        derived_variables=derived,
        pattern_report=pattern_report,
        show_progress=not args.quiet,
        engine=args.engine,
    )
    
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump({"questions": result}, f, indent=2)
    
    print(f"\nResult saved to: {args.output}")


if __name__ == "__main__":
    main()
