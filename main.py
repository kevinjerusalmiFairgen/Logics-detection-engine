#!/usr/bin/env python3
"""
Survey Digitization Pipeline - Main Orchestrator

Executes all 7 steps to convert PDF questionnaires and datasets
into machine-readable JSON with complete logic mapping.

Usage:
    python main.py --pdf survey.pdf --dataset data.sav
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Import step modules
from s1_extract_pdf import extract_pdf_structure
from s2_extract_dataset import extract_dataset_metadata, get_all_variable_names
from s3_mapping import map_questions_to_variables
from s4_resolve import resolve_unmapped_variables
from s5_logic import extract_logic_and_routing
from s6_assemble import assemble_final_json, clean_json_for_output
from s7_validate import validate_final_output, print_report


def ensure_output_dir() -> Path:
    """Create output directory."""
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    return output_dir


def run_pipeline(
    pdf_path: str,
    dataset_path: str,
    output_path: str = None,
    save_intermediates: bool = False,
    show_progress: bool = True,
    skip_validation: bool = False
) -> dict:
    """Run the complete 7-step pipeline."""
    output_dir = ensure_output_dir()
    output_path = output_path or str(output_dir / "questionnaire_final.json")
    
    print("=" * 60)
    print("SURVEY DIGITIZATION PIPELINE")
    print("=" * 60)
    print(f"PDF: {pdf_path}")
    print(f"Dataset: {dataset_path}")
    print(f"Output: {output_path}")
    print("=" * 60)
    
    # =========================================================================
    # Step 1: PDF Extraction
    # =========================================================================
    print("\n[Step 1] PDF Extraction with Manus Vision...")
    
    questionnaire_structure = extract_pdf_structure(pdf_path, show_progress=show_progress)
    
    print(f"  Sections: {len(questionnaire_structure.get('sections', []))}")
    print(f"  Questions: {len(questionnaire_structure.get('questions', []))}")
    print(f"  Logic instructions: {len(questionnaire_structure.get('logic_instructions', []))}")
    
    if save_intermediates:
        with open(output_dir / "s1_pdf_structure.json", "w") as f:
            json.dump(questionnaire_structure, f, indent=2)
    
    # =========================================================================
    # Step 2: Dataset Extraction
    # =========================================================================
    print("\n[Step 2] Dataset Metadata Extraction...")
    
    dataset_inventory = extract_dataset_metadata(dataset_path)
    
    print(f"  Variables: {len(dataset_inventory)}")
    
    if save_intermediates:
        with open(output_dir / "s2_dataset_inventory.json", "w") as f:
            json.dump({"variables": dataset_inventory}, f, indent=2)
    
    # =========================================================================
    # Step 3: Question-to-Variable Mapping
    # =========================================================================
    print("\n[Step 3] Question-to-Variable Mapping...")
    
    mapping_result = map_questions_to_variables(
        dataset_inventory,
        questionnaire_structure,
        show_progress=show_progress
    )
    
    print(f"  Questions mapped: {len(mapping_result.get('questions_mapped', []))}")
    print(f"  Unmapped vars: {len(mapping_result.get('unmapped_vars', []))}")
    
    if save_intermediates:
        with open(output_dir / "s3_mapping.json", "w") as f:
            json.dump(mapping_result, f, indent=2)
    
    # =========================================================================
    # Step 4: Unmapped Variable Resolution
    # =========================================================================
    print("\n[Step 4] Unmapped Variable Resolution...")
    
    resolution_result = resolve_unmapped_variables(
        mapping_result.get("questions_mapped", []),
        mapping_result.get("unmapped_vars", []),
        dataset_inventory,
        show_progress=show_progress
    )
    
    print(f"  Derived variables: {len(resolution_result.get('derived_variables', []))}")
    print(f"  Questions updated: {len(resolution_result.get('questions_updated', []))}")
    
    if save_intermediates:
        with open(output_dir / "s4_resolution.json", "w") as f:
            json.dump(resolution_result, f, indent=2)
    
    # =========================================================================
    # Step 5: Logic Extraction and Routing Expansion
    # =========================================================================
    print("\n[Step 5] Logic Extraction and Routing Expansion...")
    
    questions_with_logic = extract_logic_and_routing(
        resolution_result.get("questions_updated", []),
        questionnaire_structure.get("logic_instructions", []),
        resolution_result.get("derived_variables", []),  # Pass recodes so logic can reference them
        show_progress=show_progress
    )
    
    total_logics = sum(len(q.get("logics", [])) for q in questions_with_logic)
    print(f"  Questions: {len(questions_with_logic)}")
    print(f"  Total logic rules: {total_logics}")
    
    if save_intermediates:
        with open(output_dir / "s5_logic.json", "w") as f:
            json.dump({"questions": questions_with_logic}, f, indent=2)
    
    # =========================================================================
    # Step 6: Assembly
    # =========================================================================
    print("\n[Step 6] Final JSON Assembly...")
    
    final_json = assemble_final_json(
        resolution_result.get("derived_variables", []),
        questions_with_logic
    )
    final_json = clean_json_for_output(final_json)
    
    print(f"  Derived variables: {len(final_json.get('derived_variables', []))}")
    print(f"  Questions: {len(final_json.get('questions', []))}")
    
    # =========================================================================
    # Step 7: Validation
    # =========================================================================
    if not skip_validation:
        print("\n[Step 7] Validation (14 Checks)...")
        
        is_valid, report = validate_final_output(
            final_json,
            get_all_variable_names(dataset_inventory),
            questionnaire_structure.get("questions", []),
            questionnaire_structure.get("logic_instructions", [])
        )
        
        print_report(report)
        
        if not is_valid:
            print("\nWARNING: Validation failed.")
    else:
        print("\n[Step 7] Skipping validation...")
    
    # =========================================================================
    # Write Output
    # =========================================================================
    print("\n" + "=" * 60)
    print("WRITING OUTPUT")
    print("=" * 60)
    
    with open(output_path, "w") as f:
        json.dump(final_json, f, indent=2)
    
    print(f"Final JSON: {output_path}")
    
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    
    return final_json


def main():
    parser = argparse.ArgumentParser(
        description="Survey Digitization Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --pdf survey.pdf --dataset data.sav
  python main.py --pdf survey.pdf --dataset data.sav --save-intermediates
  python main.py --pdf survey.pdf --dataset data.sav --output custom.json
        """
    )
    
    parser.add_argument("--pdf", "-p", required=True, help="Path to PDF questionnaire")
    parser.add_argument("--dataset", "-d", required=True, help="Path to dataset (.sav, .csv, .xlsx)")
    parser.add_argument("--output", "-o", help="Output path (default: output/questionnaire_final.json)")
    parser.add_argument("--save-intermediates", "-i", action="store_true", help="Save intermediate results")
    parser.add_argument("--skip-validation", action="store_true", help="Skip validation step")
    parser.add_argument("--quiet", "-q", action="store_true", help="Reduce output")
    
    args = parser.parse_args()
    
    load_dotenv()
    
    if not os.path.exists(args.pdf):
        print(f"Error: PDF not found: {args.pdf}")
        sys.exit(1)
    
    if not os.path.exists(args.dataset):
        print(f"Error: Dataset not found: {args.dataset}")
        sys.exit(1)
    
    if not os.getenv("MANUS_API_KEY"):
        print("Error: MANUS_API_KEY not set")
        sys.exit(1)
    
    try:
        run_pipeline(
            pdf_path=args.pdf,
            dataset_path=args.dataset,
            output_path=args.output,
            save_intermediates=args.save_intermediates,
            show_progress=not args.quiet,
            skip_validation=args.skip_validation
        )
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
