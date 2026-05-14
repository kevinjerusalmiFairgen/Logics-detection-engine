#!/usr/bin/env python3
"""
Survey Digitization Pipeline - Main Orchestrator

Executes all 8 steps to convert PDF questionnaires and datasets
into machine-readable JSON with complete logic mapping.

Steps: 1 PDF, 2 Dataset, 3 Mapping, 4 Resolution, 5 Pattern Discovery,
       6 Logic, 7 Assemble, 8 Validate.

Usage:
    python main.py --pdf survey.pdf --dataset data.sav
    python main.py --pdf survey.pdf --dataset data.sav --from-step 4 --save-intermediates
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Import step modules
from logic_platform.digitization.steps.s1_extract_pdf import extract_pdf_structure
from logic_platform.digitization.steps.s2_extract_dataset import extract_dataset_metadata, get_all_variable_names
from logic_platform.digitization.steps.s3_mapping import map_questions_to_variables
from logic_platform.digitization.steps.s4_resolve import resolve_unmapped_variables
from logic_platform.digitization.steps.s5_pattern_discovery import run_pattern_discovery
from logic_platform.digitization.steps.s6_logic import extract_logic_and_routing
from logic_platform.digitization.steps.s7_assemble import assemble_final_json, clean_json_for_output
from logic_platform.digitization.steps.s8_validate import validate_final_output, print_report


def _print_step_cost(cost_info, step_num: int) -> None:
    """Print cost for a step. cost_info: int (credits), dict with credits, or dict with tokens."""
    if cost_info is None:
        return
    if isinstance(cost_info, dict):
        if "credits" in cost_info:
            print(f"  Credits used: {cost_info['credits']}")
        elif "input_tokens" in cost_info:
            from logic_platform.opus_utils import estimate_opus_cost
            c = estimate_opus_cost(cost_info["input_tokens"], cost_info["output_tokens"])
            print(f"  Tokens: {cost_info['input_tokens']} in, {cost_info['output_tokens']} out (~${c:.4f})")
    elif isinstance(cost_info, (int, float)):
        print(f"  Credits used: {cost_info}")


def ensure_output_dir() -> Path:
    """Create output directory."""
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    return output_dir


def _intermediate_file(intermediate_dir: Path, name: str) -> Path:
    return intermediate_dir / name


def _require_resume_file(path: Path, from_step: int) -> None:
    if not path.is_file():
        raise FileNotFoundError(
            f"--from-step {from_step} requires existing file: {path}\n"
            "Run once with --save-intermediates (same --intermediate-dir), or copy JSON artifacts there."
        )


def run_pipeline(
    pdf_path: str,
    dataset_path: str,
    output_path: str = None,
    save_intermediates: bool = False,
    show_progress: bool = True,
    skip_validation: bool = False,
    engine: str = "opus",
    from_step: int = 1,
    intermediate_dir: str = "output",
) -> dict:
    """Run the complete 8-step pipeline. engine: opus (default) or manus.

    If from_step > 1, prior steps load JSON from intermediate_dir (no LLM cost
    for those steps). Use after a failure or to re-run only later steps.
    """
    llm_engine = engine

    resume_root = Path(intermediate_dir)
    output_dir = resume_root if save_intermediates else ensure_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_path or str(output_dir / "questionnaire_final.json")
    if llm_engine == "manus":
        os.environ["LOGIC_PLATFORM_MANUS_TASK_REGISTRY"] = str(output_dir / "manus_tasks.json")

    print("=" * 60)
    print("SURVEY DIGITIZATION PIPELINE")
    print("=" * 60)
    print(f"PDF: {pdf_path}")
    print(f"Dataset: {dataset_path}")
    print(f"Output: {output_path}")
    print(f"LLM engine: {llm_engine} (Step 1 + Steps 3-6)")
    if from_step > 1:
        print(f"RESUME: from step {from_step} (steps < {from_step} from {resume_root.resolve()})")
    print("=" * 60)
    
    credits_breakdown = {}
    _skipped = {"credits": 0} if llm_engine == "manus" else {"input_tokens": 0, "output_tokens": 0}
    
    # =========================================================================
    # Step 1: PDF Extraction
    # =========================================================================
    if from_step <= 1:
        engine_label = "Claude Opus 4.6" if llm_engine == "opus" else "Manus Vision"
        print(f"\n[Step 1] PDF Extraction ({engine_label})...")

        questionnaire_structure, credits_breakdown[1] = extract_pdf_structure(
            pdf_path, show_progress=show_progress, engine=llm_engine
        )
        
        print(f"  Sections: {len(questionnaire_structure.get('sections', []))}")
        _print_step_cost(credits_breakdown.get(1), 1)
        print(f"  Questions: {len(questionnaire_structure.get('questions', []))}")
        print(f"  Logic instructions: {len(questionnaire_structure.get('logic_instructions', []))}")
        
        if save_intermediates:
            with open(output_dir / "s1_pdf_structure.json", "w") as f:
                json.dump(questionnaire_structure, f, indent=None)
    else:
        p1 = _intermediate_file(resume_root, "s1_pdf_structure.json")
        _require_resume_file(p1, from_step)
        print(f"\n[Step 1] PDF Extraction — skipped (loaded from {p1})")
        with open(p1) as f:
            questionnaire_structure = json.load(f)
        credits_breakdown[1] = _skipped
        print(f"  Sections: {len(questionnaire_structure.get('sections', []))}")
        print(f"  Questions: {len(questionnaire_structure.get('questions', []))}")
        print(f"  Logic instructions: {len(questionnaire_structure.get('logic_instructions', []))}")
    
    # =========================================================================
    # Step 2: Dataset Extraction
    # =========================================================================
    if from_step <= 2:
        print("\n[Step 2] Dataset Metadata Extraction...")
        
        dataset_inventory = extract_dataset_metadata(dataset_path)
        
        print(f"  Variables: {len(dataset_inventory)}")
        
        if save_intermediates:
            with open(output_dir / "s2_dataset_inventory.json", "w") as f:
                json.dump({"variables": dataset_inventory}, f, indent=None)
    else:
        p2 = _intermediate_file(resume_root, "s2_dataset_inventory.json")
        _require_resume_file(p2, from_step)
        print(f"\n[Step 2] Dataset Metadata Extraction — skipped (loaded from {p2})")
        with open(p2) as f:
            inv_raw = json.load(f)
        dataset_inventory = inv_raw["variables"] if isinstance(inv_raw, dict) else inv_raw
        print(f"  Variables: {len(dataset_inventory)}")
    
    # =========================================================================
    # Step 3: Question-to-Variable Mapping
    # =========================================================================
    if from_step <= 3:
        print("\n[Step 3] Question-to-Variable Mapping...")
        
        mapping_result, credits_breakdown[3] = map_questions_to_variables(
            dataset_inventory,
            questionnaire_structure,
            show_progress=show_progress,
            engine=llm_engine,
        )
        
        print(f"  Questions mapped: {len(mapping_result.get('questions_mapped', []))}")
        print(f"  Unmapped vars: {len(mapping_result.get('unmapped_vars', []))}")
        _print_step_cost(credits_breakdown[3], 3)
        
        if save_intermediates:
            with open(output_dir / "s3_mapping.json", "w") as f:
                json.dump(mapping_result, f, indent=None)
    else:
        p3 = _intermediate_file(resume_root, "s3_mapping.json")
        _require_resume_file(p3, from_step)
        print(f"\n[Step 3] Question-to-Variable Mapping — skipped (loaded from {p3})")
        with open(p3) as f:
            mapping_result = json.load(f)
        credits_breakdown[3] = _skipped
        print(f"  Questions mapped: {len(mapping_result.get('questions_mapped', []))}")
        print(f"  Unmapped vars: {len(mapping_result.get('unmapped_vars', []))}")
    
    # =========================================================================
    # Step 4: Unmapped Variable Resolution
    # =========================================================================
    if from_step <= 4:
        print("\n[Step 4] Unmapped Variable Resolution...")
        
        resolution_result, credits_breakdown[4] = resolve_unmapped_variables(
            mapping_result.get("questions_mapped", []),
            mapping_result.get("unmapped_vars", []),
            dataset_inventory,
            show_progress=show_progress,
            engine=llm_engine,
        )
        
        print(f"  Derived variables: {len(resolution_result.get('derived_variables', []))}")
        print(f"  Questions updated: {len(resolution_result.get('questions_updated', []))}")
        _print_step_cost(credits_breakdown[4], 4)
        
        if save_intermediates:
            with open(output_dir / "s4_resolution.json", "w") as f:
                json.dump(resolution_result, f, indent=None)
    else:
        p4 = _intermediate_file(resume_root, "s4_resolution.json")
        _require_resume_file(p4, from_step)
        print(f"\n[Step 4] Unmapped Variable Resolution — skipped (loaded from {p4})")
        with open(p4) as f:
            resolution_result = json.load(f)
        credits_breakdown[4] = _skipped
        print(f"  Derived variables: {len(resolution_result.get('derived_variables', []))}")
        print(f"  Questions updated: {len(resolution_result.get('questions_updated', []))}")
    
    # =========================================================================
    # Step 5: Pattern Discovery
    # =========================================================================
    if from_step <= 5:
        print("\n[Step 5] Pattern Discovery...")
        
        pattern_report, credits_breakdown[5] = run_pattern_discovery(
            resolution_result.get("questions_updated", []),
            dataset_inventory,
            questionnaire_structure.get("logic_instructions", []),
            resolution_result.get("derived_variables", []),
            show_progress=show_progress,
            engine=llm_engine,
        )
        
        print(f"  Exclusive anchors: {len(pattern_report.get('exclusive_anchors', []))}")
        print(f"  Recode patterns: {len(pattern_report.get('recode_patterns', []))}")
        _print_step_cost(credits_breakdown[5], 5)
        
        if save_intermediates:
            with open(output_dir / "s5_pattern_report.json", "w") as f:
                json.dump(pattern_report, f, indent=None)
    else:
        p5 = _intermediate_file(resume_root, "s5_pattern_report.json")
        _require_resume_file(p5, from_step)
        print(f"\n[Step 5] Pattern Discovery — skipped (loaded from {p5})")
        with open(p5) as f:
            pattern_report = json.load(f)
        credits_breakdown[5] = _skipped
        print(f"  Exclusive anchors: {len(pattern_report.get('exclusive_anchors', []))}")
        print(f"  Recode patterns: {len(pattern_report.get('recode_patterns', []))}")
    
    # =========================================================================
    # Step 6: Logic Extraction and Routing Expansion
    # =========================================================================
    if from_step <= 6:
        print("\n[Step 6] Logic Extraction and Routing Expansion...")
        
        questions_updated = resolution_result.get("questions_updated", [])
        questions_with_logic, credits_breakdown[6] = extract_logic_and_routing(
            questions_updated,
            questionnaire_structure.get("logic_instructions", []),
            derived_variables=resolution_result.get("derived_variables", []),
            pattern_report=pattern_report,
            show_progress=show_progress,
            engine=llm_engine,
        )
    else:
        p6 = _intermediate_file(resume_root, "s6_logic.json")
        _require_resume_file(p6, from_step)
        print(f"\n[Step 6] Logic Extraction and Routing Expansion — skipped (loaded from {p6})")
        with open(p6) as f:
            s6_raw = json.load(f)
        questions_with_logic = (
            s6_raw["questions"] if isinstance(s6_raw, dict) else s6_raw
        )
        questions_updated = resolution_result.get("questions_updated", [])
        credits_breakdown[6] = _skipped
    
    if questions_updated and not questions_with_logic:
        raise RuntimeError(
            "Logic step returned 0 questions (expected %d). "
            "Manus may have saved the wrong output file. Check that logic_output.json "
            "is produced, not pattern_report.json." % len(questions_updated)
        )
    
    total_logics = sum(len(q.get("logics", [])) for q in questions_with_logic)
    print(f"  Questions: {len(questions_with_logic)}")
    print(f"  Total logic rules: {total_logics}")
    _print_step_cost(credits_breakdown[6], 6)
    
    if save_intermediates:
        with open(output_dir / "s6_logic.json", "w") as f:
            json.dump({"questions": questions_with_logic}, f, indent=None)
    
    # =========================================================================
    # Step 7: Assembly
    # =========================================================================
    print("\n[Step 7] Final JSON Assembly...")

    n_logics_before = sum(len(q.get("logics") or []) for q in questions_with_logic)
    final_json = assemble_final_json(
        resolution_result.get("derived_variables", []),
        questions_with_logic
    )
    n_logics_after = sum(len(q.get("logics") or []) for q in final_json["questions"])
    n_recodes = n_logics_after - n_logics_before
    if n_recodes:
        print(f"  Materialized {n_recodes} recode logic row(s) from derived_variables.")

    final_json = clean_json_for_output(final_json)
    
    print(f"  Derived variables: {len(final_json.get('derived_variables', []))}")
    print(f"  Questions: {len(final_json.get('questions', []))}")
    
    # =========================================================================
    # Step 8: Validation
    # =========================================================================
    if not skip_validation:
        print("\n[Step 8] Validation (14 Checks)...")
        
        is_valid, report = validate_final_output(
            final_json,
            get_all_variable_names(dataset_inventory),
            questionnaire_structure.get("questions", []),
            questionnaire_structure.get("logic_instructions", []),
            pattern_report=pattern_report
        )
        
        print_report(report)
        
        if not is_valid:
            print("\nWARNING: Validation failed.")
    else:
        print("\n[Step 8] Skipping validation...")
    
    # =========================================================================
    # Write Output
    # =========================================================================
    print("\n" + "=" * 60)
    print("WRITING OUTPUT")
    print("=" * 60)
    
    with open(output_path, "w") as f:
        json.dump(final_json, f, indent=2)
    
    print(f"Final JSON: {output_path}")
    
    # =========================================================================
    # Cost Summary
    # =========================================================================
    print("\n" + "=" * 60)
    if llm_engine == "opus":
        print("OPUS (Vertex AI) TOKEN USAGE")
        print("=" * 60)
        step_names = {
            1: "Step 1: PDF Extraction", 3: "Step 3: Mapping", 4: "Step 4: Resolution",
            5: "Step 5: Pattern Discovery", 6: "Step 6: Logic"
        }
        total_in, total_out, total_cost = 0, 0, 0.0
        from logic_platform.opus_utils import estimate_opus_cost
        for step_num in [1, 3, 4, 5, 6]:
            info = credits_breakdown.get(step_num)
            if isinstance(info, dict) and "input_tokens" in info:
                total_in += info["input_tokens"]
                total_out += info["output_tokens"]
                cost = estimate_opus_cost(info["input_tokens"], info["output_tokens"])
                total_cost += cost
                print(f"  {step_names[step_num]}: {info['input_tokens']} in, {info['output_tokens']} out (~${cost:.4f})")
            else:
                print(f"  {step_names[step_num]}: (credits/tokens not tracked)")
        print("-" * 60)
        print(f"  TOTAL: ~{total_in + total_out} tokens (~${total_cost:.4f})")
    else:
        print("MANUS API CREDITS")
        print("=" * 60)
        step_names = {
            1: "Step 1: PDF Extraction", 3: "Step 3: Mapping", 4: "Step 4: Resolution",
            5: "Step 5: Pattern Discovery", 6: "Step 6: Logic"
        }
        total_credits = 0
        for step_num in [1, 3, 4, 5, 6]:
            info = credits_breakdown.get(step_num)
            c = info.get("credits", info) if isinstance(info, dict) else (info or 0)
            total_credits += c
            print(f"  {step_names[step_num]}: {c} credits")
        print("-" * 60)
        print(f"  TOTAL: {total_credits} credits")
    print("=" * 60)
    
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
  python main.py --pdf survey.pdf --dataset data.sav --engine manus --from-step 4 \\
    --intermediate-dir output --save-intermediates -o out.json
        """
    )
    
    parser.add_argument("--pdf", "-p", required=True, help="Path to PDF questionnaire")
    parser.add_argument("--dataset", "-d", required=True, help="Path to dataset (.sav, .csv, .xlsx)")
    parser.add_argument("--output", "-o", help="Output path (default: output/questionnaire_final.json)")
    parser.add_argument("--save-intermediates", "-i", action="store_true", help="Save intermediate results")
    parser.add_argument("--skip-validation", action="store_true", help="Skip validation step")
    parser.add_argument(
        "--engine", "-e",
        choices=["opus", "manus"],
        default="opus",
        help="LLM engine for all steps (1, 3-6): opus (Claude Opus 4.6, default) or manus",
    )
    parser.add_argument(
        "--from-step",
        type=int,
        default=1,
        metavar="N",
        help="Resume from step N (2-7): load s1…s(N-1) from --intermediate-dir, run N…8. Requires prior JSON artifacts.",
    )
    parser.add_argument(
        "--intermediate-dir",
        default="output",
        help="Directory with s1_pdf_structure.json, s2_dataset_inventory.json, … (default: output)",
    )
    parser.add_argument("--quiet", "-q", action="store_true", help="Reduce output")

    args = parser.parse_args()
    if args.from_step < 1 or args.from_step > 7:
        print("Error: --from-step must be between 1 and 7")
        sys.exit(1)
    
    load_dotenv()
    
    if not os.path.exists(args.pdf):
        print(f"Error: PDF not found: {args.pdf}")
        sys.exit(1)
    
    if not os.path.exists(args.dataset):
        print(f"Error: Dataset not found: {args.dataset}")
        sys.exit(1)
    
    engine = args.engine
    if engine == "manus" and not os.getenv("MANUS_API_KEY"):
        print("Error: MANUS_API_KEY not set (required for Manus)")
        sys.exit(1)
    if engine == "opus" and not os.getenv("GOOGLE_CLOUD_PROJECT"):
        print("Warning: GOOGLE_CLOUD_PROJECT not set; using default fairgen-common")
    
    try:
        run_pipeline(
            pdf_path=args.pdf,
            dataset_path=args.dataset,
            output_path=args.output,
            save_intermediates=args.save_intermediates,
            show_progress=not args.quiet,
            skip_validation=args.skip_validation,
            engine=args.engine,
            from_step=args.from_step,
            intermediate_dir=args.intermediate_dir,
        )
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
