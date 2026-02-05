#!/usr/bin/env python3
"""
Step 2: Dataset Metadata Extraction

Extracts variable metadata from SPSS (.sav), CSV, and Excel files.
Uses the existing metadata.py functionality.

Usage:
    python s2_extract_dataset.py data.sav --output phase2_result.json
"""

import json
import os
import argparse
from pathlib import Path
from typing import Dict, List

import pandas as pd
import pyreadstat


def extract_dataset_metadata(data_path: str) -> List[Dict]:
    """
    Extract all variable metadata from a dataset file.
    
    Supports: SPSS .sav, CSV, Excel .xlsx/.xls
    
    Args:
        data_path: Path to the dataset file
        
    Returns:
        List of variable metadata dictionaries
    """
    path = Path(data_path)
    suffix = path.suffix.lower()
    
    if suffix == ".sav":
        return _extract_from_spss(str(path))
    elif suffix in (".xlsx", ".xls"):
        return _extract_from_excel(str(path))
    elif suffix == ".csv":
        return _extract_from_csv(str(path))
    else:
        raise ValueError(f"Unsupported format: {suffix}")


def _extract_from_spss(filepath: str) -> List[Dict]:
    """Extract metadata from SPSS .sav file."""
    df, meta = pyreadstat.read_sav(filepath)
    
    var_labels = meta.column_names_to_labels or {}
    val_labels = meta.variable_value_labels or {}
    missing_ranges = getattr(meta, 'missing_ranges', {}) or {}
    
    inventory = []
    for i, col in enumerate(meta.column_names):
        series = df[col]
        col_labels = val_labels.get(col, {})
        
        var_type = _infer_variable_type(series, col_labels)
        
        values = None
        if col_labels:
            values = {str(k): str(v) for k, v in list(col_labels.items())[:50]}
        elif var_type == "categorical" and series.nunique() <= 50:
            values = {str(v): str(v) for v in series.dropna().unique()[:50]}
        
        inventory.append({
            "var": col,
            "label": var_labels.get(col, ""),
            "values": values,
            "missing": missing_ranges.get(col, []),
            "type": var_type,
            "order": i + 1
        })
    
    return inventory


def _extract_from_csv(filepath: str) -> List[Dict]:
    """Extract metadata from CSV file."""
    df = pd.read_csv(filepath)
    return _extract_from_dataframe(df)


def _extract_from_excel(filepath: str) -> List[Dict]:
    """Extract metadata from Excel file."""
    df = pd.read_excel(filepath)
    return _extract_from_dataframe(df)


def _extract_from_dataframe(df: pd.DataFrame) -> List[Dict]:
    """Extract metadata from pandas DataFrame."""
    inventory = []
    
    for i, col in enumerate(df.columns):
        series = df[col]
        var_type = _infer_variable_type(series, {})
        
        values = None
        if var_type == "categorical" and series.nunique() <= 50:
            values = {str(v): str(v) for v in series.dropna().unique()[:50]}
        
        inventory.append({
            "var": col,
            "label": "",
            "values": values,
            "missing": [],
            "type": var_type,
            "order": i + 1
        })
    
    return inventory


def _infer_variable_type(series: pd.Series, value_labels: Dict) -> str:
    """Infer variable type from data characteristics."""
    if value_labels:
        return "categorical"
    
    if series.dtype == "object":
        avg_len = series.dropna().astype(str).str.len().mean()
        return "text" if avg_len > 50 else "categorical"
    
    if pd.api.types.is_numeric_dtype(series):
        return "categorical" if series.nunique() <= 20 else "numeric"
    
    return "text"


def get_all_variable_names(inventory: List[Dict]) -> List[str]:
    """Get list of all variable names."""
    return [var["var"] for var in inventory]


def main():
    parser = argparse.ArgumentParser(description="Step 2: Extract dataset metadata")
    parser.add_argument("data_path", help="Path to dataset (.sav, .csv, .xlsx)")
    parser.add_argument("--output", "-o", default="output/s2_dataset_inventory.json", help="Output JSON file")
    args = parser.parse_args()
    
    print("\n[Step 2] Dataset Metadata Extraction")
    print("=" * 50)
    
    inventory = extract_dataset_metadata(args.data_path)
    
    print(f"  Variables extracted: {len(inventory)}")
    
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump({"variables": inventory}, f, indent=2, ensure_ascii=False)
    
    print(f"\nResult saved to: {args.output}")


if __name__ == "__main__":
    main()
