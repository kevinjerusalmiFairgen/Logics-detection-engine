"""Prior-file CSV → legacy ``constraints_json`` / ``structure_json`` (headless Fairset-era parser)."""

from __future__ import annotations

import ast
import re
import warnings

import pandas as pd

def normalize_quotes(text):
    replacements = {
        '‘': "'", '’': "'",
        '“': '"', '”': '"',
        '‚': "'", '‛': "'",
        '„': '"', '‟': '"',
        '❝': '"', '❞': '"',
        '❮': '<', '❯': '>'
    }

    if isinstance(text, str):
        # Replace all smart quotes
        for orig, repl in replacements.items():
            text = text.replace(orig, repl)
        # Strip any surrounding quotes
        return text.strip().strip('"').strip("'")
    
    elif isinstance(text, list):
        return [normalize_quotes(item) for item in text]
    
    return text


def check_columns_presence(df_priorfile, df, cols):
    flat_list = []

    for col in cols:
        for item in df_priorfile[col]:
            if pd.isna(item):
                continue

            # Handle stringified lists
            if isinstance(item, str) and item.strip().startswith('['):
                try:
                    parsed = ast.literal_eval(item)
                    if isinstance(parsed, list):
                        flat_list.extend(parsed)
                    else:
                        flat_list.append(parsed)
                except Exception:
                    cleaned = item.strip().rstrip(']').lstrip('[').split(',')
                    flat_list.extend([x.strip().strip("'").strip('"').strip("’") for x in cleaned])

            elif isinstance(item, list):
                flat_list.extend(item)
            else:
                flat_list.append(str(item))

    # ✅ Normalize quotes BEFORE comparison
    flat_set = set(normalize_quotes(col.strip()).lower() for col in flat_list)
    df_columns = set(normalize_quotes(str(col).strip()).lower() for col in df.columns)
    missing = flat_set - df_columns

    return list(missing)
    

def cleaning_lists(target_str):
    if not isinstance(target_str, str):
        return target_str
    if target_str.startswith('['):
        clean_str = target_str.strip("[]")
        list_items = re.findall(r"/?\s*['\"’]([^'\"’]+)['\"’]\s*/?", clean_str)
        return [item.strip() for item in list_items]
    else:
        return target_str.strip()


def priorFileExtract(df):
    df = df[["Target", "Source", "Constraint", "B/F Relationship", "Comment", "Is Implemented", "Custom Query", "ID"]]
    df["Target"] = df["Target"].apply(normalize_quotes)
    df["Source"] = df["Source"].apply(normalize_quotes)
    df["Target"] = df["Target"].apply(cleaning_lists)
    df["Source"] = df["Source"].apply(cleaning_lists)

    df['ID'] = df['ID'].apply(lambda x: x['number'] if isinstance(x, dict) else x)
    df["Is Implemented"] = df["Is Implemented"] .apply(lambda x: False if x == "No" else True)

    constraints_json = {
        "BF_SS": [],
        "BF_SM": [],
        "BF_MS": [],
        "BF_MM": [],
        "uniqueness": [],
        "count": [],
        "recodings": [],
        "NOTAs": [],
        "AOTAs": [],
        "parallel piping": [],
        "custom": []
    }

    structure_json = {
        "recodings": [],
        "multiSelect": [],
        "typeOfNan": [],
    }

    for index, row in df.iterrows():
        if pd.notna(row["Custom Query"]) and row["Custom Query"] not in ['', None]:
            constraints_json["custom"].append([
                row["Constraint"],
                row["Comment"],
                row["Custom Query"],
                row["Is Implemented"]
            ])
            
        else:
            if row["Constraint"] in ["Block", "Force", "Block/Force", "Dynamic Piping"]:
                if not row["B/F Relationship"]:
                    warnings.warn(
                        f"Row #{row['ID']} not valid: missing relationship for Block/Force",
                        RuntimeWarning,
                        stacklevel=1,
                    )
                elif row["B/F Relationship"] == "Single to Single":
                    constraints_json["BF_SS"].append([
                        row["Source"],
                        row["Target"],
                        row["Comment"],
                        row["Constraint"].lower().replace("/", "_").replace(" ", "_"),
                        row["Is Implemented"]
                    ])
                elif row["B/F Relationship"] == "Single to Multi":
                    constraints_json["BF_SM"].append([
                        row["Source"],
                        row["Target"],
                        row["Comment"],
                        row["Constraint"].lower().replace("/", "_"),
                        row["Is Implemented"]
                    ])
                elif row["B/F Relationship"] == "Multi to Single":
                    constraints_json["BF_MS"].append([
                        row["Target"],
                        row["Source"],
                        row["Comment"],
                        row["Is Implemented"]
                    ])
                else:
                    warnings.warn(
                        f"Row #{row['ID']} not valid: wrong relationship for Block/Force",
                        RuntimeWarning,
                        stacklevel=1,
                    )
                    
            elif row["Constraint"] == "Parallel Piping":
                constraints_json["BF_MM"].append([
                    row["Source"],
                    row["Target"],
                    [],
                    row["Comment"],
                    "block_force",
                    row["Is Implemented"]
                ])
            elif row["Constraint"] == "Uniqueness":
                constraints_json["uniqueness"].append([
                    row["Target"],
                    row["Is Implemented"]
                ])
            elif row["Constraint"] == "Count":
                constraints_json["count"].append([
                    row["Target"],
                    row["Source"],
                    row["Is Implemented"]
                ])
            elif row["Constraint"] == "Recoding":
                if not row["B/F Relationship"]:
                    warnings.warn(
                        f"Row #{row['ID']} not valid: missing relationship for Recoding",
                        RuntimeWarning,
                        stacklevel=1,
                    )
                elif row["B/F Relationship"] == "Single to Single":
                    mode = "SS"
                    structure_json["recodings"].append(
                        {
                            "id": str(index),
                            "name": str(index),
                            "recode": row["Target"],
                            "codes": row["Source"]
                        }
                    )
                elif row["B/F Relationship"] == "Single to Multi":
                    mode = "SM"
                elif row["B/F Relationship"] == "Multi to Single":
                    mode = "MS"
                    structure_json["recodings"].append(
                        {
                            "id": str(index),
                            "name": str(index),
                            "recode": row["Target"],
                            "codes": row["Source"]
                        }
                    )
                elif row["B/F Relationship"] == "Multi to Multi":
                    mode = "MM"
                else:
                    warnings.warn(
                        f"Row #{row['ID']} not valid: wrong relationship for Recoding",
                        RuntimeWarning,
                        stacklevel=1,
                    )
                constraints_json["recodings"].append([
                    row["Source"],
                    row["Target"],
                    mode,
                    row["Comment"],
                    row["Is Implemented"]
                ])
            elif row["Constraint"] == "None of the above":
                constraints_json["NOTAs"].append([
                    row["Source"],
                    row["Target"],
                    [],
                    row["Is Implemented"]
                ])
            elif row["Constraint"] == "All of the above":
                constraints_json["AOTAs"].append([
                    row["Source"],
                    row["Target"],
                    [],
                    row["Is Implemented"]
                ])
            elif row["Constraint"] == "MultiSelect":
                structure_json["multiSelect"].append(
                    {
                        "id": str(index),
                        "name": str(index),
                        "columns": row["Target"],
                    }
                )

    return constraints_json, structure_json