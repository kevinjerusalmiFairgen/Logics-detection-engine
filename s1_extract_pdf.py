#!/usr/bin/env python3
"""
Step 1: PDF Extraction with Manus Vision (PASS 1B)

Extracts sections, question IDs, question text, routing, ask-if, 
exclusivity, min/max/exactly, sums, carry-forward/filtering rules.
Removes termination/screenout wording - keeps only eligibility predicates.

Usage:
    python s1_extract_pdf.py survey.pdf --output s1_result.json
"""

import json
import os
import argparse
from typing import Dict

from utils import ManusAPIClient, extract_json_from_task


def extract_pdf_structure(pdf_path: str, show_progress: bool = True) -> Dict:
    """
    Use Manus Vision to extract sections, questions, and logic from PDF.
    
    Args:
        pdf_path: Path to the survey PDF file
        show_progress: Whether to display progress during extraction
        
    Returns:
        Dict with keys: sections, questions, logic_instructions
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    client = ManusAPIClient()
    
    if show_progress:
        print(f"  Uploading PDF: {pdf_path}")
    
    upload_result = client.upload_file(pdf_path)
    
    if show_progress:
        print(f"  File uploaded: {upload_result.file_id}")
    
    prompt = _build_extraction_prompt()
    
    if show_progress:
        print("  Creating extraction task...")
    
    task_result = client.create_task(
        prompt=prompt,
        attachments=[{"file_id": upload_result.file_id}],
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
    
    if show_progress:
        print(f"  Extraction complete:")
        print(f"    - Sections: {len(result.get('sections', []))}")
        print(f"    - Questions: {len(result.get('questions', []))}")
        print(f"    - Logic instructions: {len(result.get('logic_instructions', []))}")
    
    return result


def _build_extraction_prompt() -> str:
    """Build the extraction prompt for Manus Vision - PASS 1B from master prompt."""
    return '''You are an expert survey programmer analyzing a survey questionnaire PDF. 
Use your vision capabilities to understand the visual structure, layout, and formatting.

Your task is PASS 1B: PDF EXTRACTION from the master prompt.

=============================================================================
EXTRACTION REQUIREMENTS
=============================================================================

Extract the following from the PDF:
- Sections (headers, IDs, page ranges)
- Question IDs and full question text
- Routing instructions (skip-to-question, skip-to-section)
- Ask-if conditions
- Exclusivity rules (none/DK/RF mutual exclusion)
- Min/max/exactly constraints on selections
- Sum/add-up constraints
- Carry-forward/filtering rules (piping)
- Grid/table structures with row and column labels

=============================================================================
CRITICAL: TERMINATION WORDING REMOVAL
=============================================================================

You MUST remove all termination/screenout wording from the output.
KEEP ONLY the eligibility predicates.

Examples of what to REMOVE:
- "Thank you for your time"
- "You do not qualify for this survey"
- "Unfortunately, we are looking for..."
- "This concludes the survey"
- "You have been screened out"
- Any "sorry" or "thank you" termination messages

Examples of what to KEEP:
- "If under 18, skip to end" → Keep condition "under 18", remove "end" destination
- "Must be employed to continue" → Keep condition "employed"
- Only extract the eligibility CONDITION, not the termination action

=============================================================================
SECTION EXTRACTION
=============================================================================

For each section, extract:
- id: Section identifier (A, B, C or 1, 2, 3 or name-based)
- title: Full section title
- page_start: Starting page number
- page_end: Ending page number
- gate_condition: Any eligibility gate for entering this section (if present)

=============================================================================
QUESTION EXTRACTION
=============================================================================

For each question, extract:
- id: Question identifier exactly as shown (Q1, Q2, D1, S1, etc.)
- section_id: Which section this question belongs to
- text: FULL question text including any instructions
- page: Page number where question appears
- order: Sequential order in the questionnaire (1, 2, 3...)
- type: One of these ONLY:
  * "numeric" - asks for a number (age, count, amount)
  * "single_select" - select ONE option from a list
  * "multi_select" - select ALL that apply (one dimension, list of options)
  * "grid" - TRUE 2-DIMENSIONAL matrix: rows × columns (e.g., brands × attributes)
  * "numeric_grid" - 2D grid where cells are numbers (e.g., brands × spend amounts)
  * "open_text" - free text response
- grid_rows: (only for grid/numeric_grid) Row labels in order
- grid_columns: (only for grid/numeric_grid) Column labels in order

IMPORTANT - GRID vs MULTI_SELECT:
- "grid" = TWO dimensions required (rows AND columns, e.g., rate 5 brands on 4 attributes)
- "multi_select" = ONE dimension only (a list of checkboxes, even if many items)
- If there's only a LIST of items to check/select → multi_select
- If there's a MATRIX with rows and a scale/columns to rate each row → grid

CRITICAL: Preserve EXACT question order as it appears in the PDF.
This order will be used for routing expansion.

=============================================================================
LOGIC INSTRUCTION EXTRACTION
=============================================================================

Extract ALL logic instructions into these categories:

1) skip_to_question
   - raw_text: Exact wording from PDF
   - source_question: Question that triggers the skip
   - target_question: Question to skip TO
   - condition: The condition that triggers the skip
   - page: Page number

2) skip_to_section
   - raw_text: Exact wording
   - source_question: Question that triggers the skip
   - target_section: Section to skip TO
   - condition: The condition
   - page: Page number

3) section_gate
   - raw_text: Exact wording
   - section_id: Section with the gate
   - condition: Eligibility condition for the section
   - page: Page number

4) ask_if
   - raw_text: Exact wording
   - target_question: Question that has the condition
   - condition: The ask-if condition
   - page: Page number

5) exclusive
   - raw_text: Exact wording
   - target_question: Question with exclusive option(s)
   - exclusive_options: Which options are exclusive (if identifiable)
   - page: Page number

6) count
   - raw_text: Exact wording (e.g., "Select exactly 3")
   - target_question: Question with the constraint
   - constraint: The min/max/exactly constraint
   - page: Page number

7) sum
   - raw_text: Exact wording (e.g., "Must add up to 100%")
   - target_question: Question with the constraint
   - constraint: The sum constraint
   - page: Page number

8) piping
   - raw_text: Exact wording
   - source_question: Question providing the selections
   - target_question: Question receiving filtered options
   - page: Page number

=============================================================================
OUTPUT FORMAT (STRICT JSON)
=============================================================================

{{
  "sections": [
    {{
      "id": "<section_id>",
      "title": "<section title from PDF>",
      "page_start": <number>,
      "page_end": <number>,
      "gate_condition": "<condition or null>"
    }}
  ],
  "questions": [
    {{
      "id": "<question_id>",
      "section_id": "<section_id>",
      "text": "<full question text>",
      "page": <number>,
      "order": <sequential number>,
      "type": "numeric|single_select|multi_select|grid|numeric_grid|open_text"
    }},
    {{
      "id": "<grid_question_id>",
      "section_id": "<section_id>",
      "text": "<grid question text>",
      "page": <number>,
      "order": <number>,
      "type": "grid",
      "grid_rows": ["<row1>", "<row2>", "..."],
      "grid_columns": ["<col1>", "<col2>", "..."]
    }}
  ],
  "logic_instructions": [
    {{
      "type": "skip_to_question",
      "raw_text": "<exact text from PDF>",
      "source_question": "<question_id>",
      "target_question": "<question_id>",
      "condition": "<condition>",
      "page": <number>
    }},
    {{
      "type": "section_gate",
      "raw_text": "<exact text>",
      "section_id": "<section_id>",
      "condition": "<eligibility condition>",
      "page": <number>
    }},
    {{
      "type": "ask_if",
      "raw_text": "<exact text>",
      "target_question": "<question_id>",
      "condition": "<condition>",
      "page": <number>
    }},
    {{
      "type": "exclusive",
      "raw_text": "<exact text>",
      "target_question": "<question_id>",
      "exclusive_options": ["<option1>", "<option2>"],
      "page": <number>
    }},
    {{
      "type": "count",
      "raw_text": "<exact text>",
      "target_question": "<question_id>",
      "constraint": "<min/max/exactly N>",
      "page": <number>
    }},
    {{
      "type": "sum",
      "raw_text": "<exact text>",
      "target_question": "<question_id>",
      "constraint": "<sum constraint>",
      "page": <number>
    }},
    {{
      "type": "piping",
      "raw_text": "<exact text>",
      "source_question": "<question_id>",
      "target_question": "<question_id>",
      "page": <number>
    }}
  ]
}}

=============================================================================
CRITICAL RULES
=============================================================================

1) Preserve EXACT question order from PDF - this is essential for routing expansion
2) Extract the COMPLETE question text including instructions
3) DO NOT include termination/screenout wording - only eligibility conditions
4) Capture EVERY routing instruction, no matter how small
5) For grids, preserve the exact row and column order from the PDF
6) Note exclusive options (None/DK/RF) which typically cannot combine with others
7) Identify min/max/exactly constraints on multi-select questions
8) Extract section eligibility gates

=============================================================================
FINAL STEP - SAVE OUTPUT
=============================================================================

After extracting all sections, questions, and logic instructions:
SAVE your result to a file named: pdf_structure.json

The file must be a valid JSON object with exactly three keys:
- "sections": array of section objects
- "questions": array of question objects  
- "logic_instructions": array of logic instruction objects
'''


def main():
    parser = argparse.ArgumentParser(description="Step 1: Extract PDF structure with Manus Vision")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument("--output", "-o", default="output/s1_pdf_structure.json", help="Output JSON file")
    parser.add_argument("--quiet", "-q", action="store_true", help="Reduce output")
    args = parser.parse_args()
    
    from dotenv import load_dotenv
    load_dotenv()
    
    print("\n[Step 1] PDF Extraction with Manus Vision (PASS 1B)")
    print("=" * 50)
    
    result = extract_pdf_structure(args.pdf_path, show_progress=not args.quiet)
    
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)
    
    print(f"\nResult saved to: {args.output}")


if __name__ == "__main__":
    main()
