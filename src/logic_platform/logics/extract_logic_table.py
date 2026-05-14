#!/usr/bin/env python3
"""
Extract all logic information from questionnaire_final.json into a tabular format.
Appends one multiselect row per `multi_select` question in the questionnaire. When a Step 5
pattern report is present, matching `multiselect_groups` entries enrich the Comment
(`structure_note`) only; all groups still come from the questionnaire. Applies
`materialize_recode_logics` so derived recodes appear as `recode` logics
(idempotent if the questionnaire was already assembled with Step 7).

Output CSV columns (exact headers):
  Target, Source, Constraint, B/F Relationship, Comment, Is Implemented, Custom Query, ID

Constraint must be one of the allowed UI labels. Source/Target: a single plain string if
one name; if several, a Python list literal like ['a', 'b'] (repr per element, commas OK —
CSV writer quotes the cell). Custom Query is always empty. Is Implemented is always 1.
ID is a decimal string 1, 2, 3, … per row.

Usage:
    python extract_logic_table.py [--input output/questionnaire_final.json] [--output logic_table.csv] [--format csv|table]
"""

import csv
import json
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional

from logic_platform.utils import flatten_vars
from logic_platform.digitization.steps.s7_assemble import materialize_recode_logics

MULTISELECT_LOGIC_TYPE = "multiselect"

# Allowed Constraint values (from product UI)
ALLOWED_CONSTRAINTS = frozenset(
    {
        "Block/Force",
        "Sum",
        "Padding",
        "Count",
        "Uniqueness",
        "None of the above",
        "All of the above",
        "Parallel Piping",
        "Block",
        "Force",
        "Recoding",
        "MultiSelect",
        "Dynamic Piping",
        "Compound Block",
        "Compound Force",
    }
)

BF_OPTIONS = frozenset(
    {"Multi to Multi", "Multi to Single", "Single to Multi", "Single to Single"}
)

CSV_FIELDNAMES = [
    "Target",
    "Source",
    "Constraint",
    "B/F Relationship",
    "Comment",
    "Is Implemented",
    "Custom Query",
    "ID",
]


def _join_slots(parts: List[str]) -> str:
    """Internal storage: semicolon-joined tokens (stable dedup keys)."""
    cleaned = [str(p).strip() for p in parts if str(p).strip()]
    return ";".join(cleaned)


def _slot_parts(cell: str) -> List[str]:
    if not (cell or "").strip():
        return []
    return [x.strip() for x in cell.split(";") if x.strip()]


def _format_slot_export(cell: str) -> str:
    """One name → plain string; several → Python list of strings, e.g. ['x', 'y']."""
    parts = _slot_parts(cell)
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "[" + ", ".join(repr(p) for p in parts) + "]"


def _count_slots(cell: str) -> int:
    return len(_slot_parts(cell))


def _bf_relationship(source_cell: str, target_cell: str) -> str:
    ns = _count_slots(source_cell)
    nt = _count_slots(target_cell)
    if ns <= 1 and nt <= 1:
        return "Single to Single"
    if ns > 1 and nt <= 1:
        return "Multi to Single"
    if ns <= 1 and nt > 1:
        return "Single to Multi"
    return "Multi to Multi"


def _sanitize_comment(text: str) -> str:
    """Avoid double-quotes and newlines breaking downstream consumers."""
    t = (text or "").replace("\r", " ").replace("\n", " ").replace('"', "'")
    return t.strip()


def _map_constraint(raw_logic_type: str, comment: str) -> str:
    t = (raw_logic_type or "").strip()
    c = (comment or "").lower()

    if t == MULTISELECT_LOGIC_TYPE:
        return "MultiSelect"
    if t in ("skip", "section_skip"):
        return "Block"
    if t == "count":
        return "Count"
    if t == "sum":
        return "Sum"
    if t == "piping":
        if "dynamic" in c or "insert" in c or "wording" in c:
            return "Dynamic Piping"
        return "Parallel Piping"
    if t == "exclusive":
        if "all of the above" in c or "consider all" in c:
            return "All of the above"
        if "none of the above" in c:
            return "None of the above"
        return "Uniqueness"
    if t == "recode":
        return "Recoding"
    if t == "custom":
        if "force" in c:
            return "Compound Force"
        return "Compound Block"
    return "Block/Force"


def extract_all_logics(questionnaire_json: Dict) -> List[Dict]:
    """
    Returns internal rows: target, source, description, logic_type (raw after section_skip->skip).
    """
    all_logics: List[Dict] = []

    for question in questionnaire_json.get("questions", []):
        for logic in question.get("logics", []):
            logic_type = logic.get("type", "")
            if logic_type == "section_skip":
                logic_type = "skip"
            logic_entry = {
                "source": _join_slots([str(x) for x in (logic.get("source_vars") or [])]),
                "target": _join_slots([str(x) for x in (logic.get("target_vars") or [])]),
                "description": logic.get("condition", ""),
                "logic_type": logic_type,
            }
            all_logics.append(logic_entry)

    seen: set = set()
    unique: List[Dict] = []
    for logic in all_logics:
        key = (logic["source"], logic["target"], logic["description"], logic["logic_type"])
        if key not in seen:
            seen.add(key)
            unique.append(logic)
    return unique


def extract_multiselect_group_rows(
    questionnaire_json: Dict, pattern_report: Optional[Dict[str, Any]] = None
) -> List[Dict]:
    out: List[Dict] = []
    questions = questionnaire_json.get("questions", [])

    groups = (pattern_report or {}).get("multiselect_groups") or []
    pattern_by_qid: Dict[str, Dict[str, Any]] = {}
    for g in groups:
        qid_raw = str(g.get("question_id") or "").strip()
        if qid_raw:
            pattern_by_qid[qid_raw] = g

    ms_qids_from_json: set = set()
    for q in questions:
        if q.get("type") != "multi_select":
            continue
        flat = [str(x) for x in flatten_vars(q.get("vars", []))]
        if not flat:
            continue
        qid = str(q.get("id", "") or "").strip()
        ms_qids_from_json.add(qid)
        text = (q.get("text") or "")[:300]
        description = f"{qid}: {text}".strip() or qid
        if qid in pattern_by_qid:
            note = (pattern_by_qid[qid].get("structure_note") or "").strip()
            if note:
                description = f"{qid}: {note}" if qid else note
        out.append(
            {
                "source": "",
                "target": _join_slots(flat),
                "description": description,
                "logic_type": MULTISELECT_LOGIC_TYPE,
            }
        )

    for g in groups:
        qid = str(g.get("question_id") or "").strip()
        if not qid or qid in ms_qids_from_json:
            continue
        vars_ = [str(v) for v in (g.get("vars") or [])]
        excl = [str(v) for v in (g.get("exclusive_vars") or [])]
        note = (g.get("structure_note") or "").strip()
        ordered: List[str] = []
        for v in vars_ + excl:
            if v.strip() and v not in ordered:
                ordered.append(v)
        if not ordered:
            continue
        out.append(
            {
                "source": "",
                "target": _join_slots(ordered),
                "description": f"{qid}: {note}" if (qid or note) else "multiselect group",
                "logic_type": MULTISELECT_LOGIC_TYPE,
            }
        )

    seen: set = set()
    unique: List[Dict] = []
    for row in out:
        key = (row["source"], row["target"], row["description"], row["logic_type"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _internal_to_export_rows(internal: List[Dict]) -> List[Dict]:
    """Add Constraint, B/F Relationship, fixed placeholders; column order for CSV."""
    export: List[Dict] = []
    for i, row in enumerate(internal, start=1):
        comment = _sanitize_comment(row.get("description", ""))
        constraint = _map_constraint(row.get("logic_type", ""), comment)
        if constraint not in ALLOWED_CONSTRAINTS:
            constraint = "Block/Force"
        src = row.get("source", "")
        tgt = row.get("target", "")
        bf = _bf_relationship(src, tgt)
        if bf not in BF_OPTIONS:
            bf = "Single to Single"
        export.append(
            {
                "Target": _format_slot_export(tgt),
                "Source": _format_slot_export(src),
                "Constraint": constraint,
                "B/F Relationship": bf,
                "Comment": comment,
                "Is Implemented": "1",
                "Custom Query": "",
                "ID": str(i),
            }
        )
    return export


def save_as_csv(rows: List[Dict], output_path: str) -> None:
    if not rows:
        print("No rows to export.")
        return
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=CSV_FIELDNAMES,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
        )
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in CSV_FIELDNAMES})
    print(f"Exported {len(rows)} rows to {output_path}")


def print_as_table(rows: List[Dict]) -> None:
    if not rows:
        print("No rows.")
        return
    print("\n" + "=" * 100)
    print(
        f"{'Target':<28} | {'Source':<28} | {'Constraint':<18} | {'B/F':<16} | {'Comment':<30}"
    )
    print("=" * 100)
    for r in rows:
        tgt = (r.get("Target", "") or "")[:26]
        src = (r.get("Source", "") or "")[:26]
        con = (r.get("Constraint", "") or "")[:16]
        bf = (r.get("B/F Relationship", "") or "")[:14]
        com = (r.get("Comment", "") or "")[:28]
        print(f"{tgt:<28} | {src:<28} | {con:<18} | {bf:<16} | {com:<30}")


def print_summary(rows: List[Dict]) -> None:
    print("\n" + "=" * 60)
    print("LOGIC EXTRACTION SUMMARY")
    print("=" * 60)
    print(f"Total rows: {len(rows)}")
    if not rows:
        return
    by_c: Dict[str, int] = {}
    for r in rows:
        c = r.get("Constraint", "unknown")
        by_c[c] = by_c.get(c, 0) + 1
    print("\nConstraint counts:")
    for k, v in sorted(by_c.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract logic + multiselect groups to CSV (Target, Source, Constraint, ...)"
    )
    parser.add_argument(
        "--input",
        "-i",
        default="output/questionnaire_final.json",
        help="Input JSON file (default: output/questionnaire_final.json)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="output/logic_table.csv",
        help="Output CSV file (default: output/logic_table.csv)",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["csv", "table", "both"],
        default="both",
        help="Output format: csv, table, or both (default: both)",
    )
    parser.add_argument("--summary", "-s", action="store_true", help="Print summary statistics")
    parser.add_argument(
        "--pattern-report",
        "-p",
        default="",
        help="Step 5 pattern JSON. Default: s5_pattern_report.json next to --input if present.",
    )
    parser.add_argument(
        "--no-multiselect-groups",
        action="store_true",
        help="Omit multiselect group rows.",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        return 1

    print(f"Loading questionnaire from: {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        questionnaire_json = json.load(f)

    materialize_recode_logics(
        questionnaire_json.get("questions", []),
        questionnaire_json.get("derived_variables", []),
    )

    pattern_path: Optional[Path] = None
    if args.pattern_report:
        pattern_path = Path(args.pattern_report)
    else:
        default_pr = input_path.parent / "s5_pattern_report.json"
        if default_pr.is_file():
            pattern_path = default_pr

    pattern_report: Optional[Dict] = None
    if pattern_path and pattern_path.is_file():
        print(f"Loading pattern report from: {pattern_path}")
        with open(pattern_path, "r", encoding="utf-8") as f:
            pattern_report = json.load(f)
    elif not args.no_multiselect_groups:
        print("No pattern report file found; multiselect groups from JSON questions only.")

    print("Extracting logic entries...")
    internal = extract_all_logics(questionnaire_json)
    if not args.no_multiselect_groups:
        ms = extract_multiselect_group_rows(questionnaire_json, pattern_report)
        print(f"Appending {len(ms)} multiselect group row(s).")
        internal = internal + ms
    else:
        print("Skipping multiselect group rows (--no-multiselect-groups).")

    export_rows = _internal_to_export_rows(internal)

    if args.summary or args.format in ["table", "both"]:
        print_summary(export_rows)

    if args.format in ["csv", "both"]:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        save_as_csv(export_rows, str(output_path))

    if args.format in ["table", "both"]:
        print_as_table(export_rows)

    return 0


if __name__ == "__main__":
    exit(main())
