import math
import numpy as np
import pandas as pd
from tqdm import tqdm
import warnings
import streamlit as st
import traceback

warnings.filterwarnings("ignore")

class LogicFunctions:

    @staticmethod
    def _convert_to_numeric(df):
        """Convert columns to numeric where possible, element by element."""
        def try_numeric(val):
            if pd.isna(val):
                return val
            try:
                return float(val)
            except (ValueError, TypeError):
                return val
        
        result = df.copy()
        for col in result.columns:
            result[col] = result[col].apply(try_numeric)
        return result

    def __init__(self, name, train, fairset, empty_values, format=None):
        self.name = name
        self.train = train.copy()
        self.fairset = fairset.copy()
        self.train.replace(empty_values, np.nan, inplace=True)
        self.fairset.replace(empty_values, np.nan, inplace=True)
        self.format = format
        self.wrong_rows = set()
        
        # Convert all columns to numeric where possible to avoid type comparison errors
        self.train = self._convert_to_numeric(self.train)
        self.fairset = self._convert_to_numeric(self.fairset)


    def detect_violations_SS(self, col1, col2, detail, block_force, is_supported=True):
        train = self.train.copy()
        fairset = self.fairset.copy()

        if train[col1].isna().all() or train[col2].isna().all() or fairset[col1].isna().all():
            return {
                "Type": "Block Single-to-Single",
                "Description": f"Block Single-to-Single ({col1} to {col2}) - All values are NaN",
                "is_valid": True,
                "is_supported": is_supported,
                "Dataframe": None,
                "Detail": detail,
                "Occurrences_train": 0,
                "Percentage_of_valid_rows": 100.0,
            }

        # Converting to strings for mixed type
        train[col1] = train[col1].apply(lambda x: str(x) if pd.notna(x) else x)
        train[col2] = train[col2].apply(lambda x: str(x) if pd.notna(x) else x)

        fairset[col1] = fairset[col1].apply(lambda x: str(x) if pd.notna(x) else x)
        fairset[col2] = fairset[col2].apply(lambda x: str(x) if pd.notna(x) else x)

        if block_force == "dynamic_piping":
            valid_combinations = set(train[[col1, col2]].drop_duplicates().itertuples(index=False, name=None))

            violations = fairset[~fairset[[col1, col2]].apply(tuple, axis=1).isin(valid_combinations)][[col1, col2]]
            violations = violations.dropna(subset=[col2])

            wrong_rows_dynamic = violations.index.tolist()

            # Adding the wrong rows for stats
            self.wrong_rows.update(wrong_rows_dynamic)
            valid_rows_dynamic = round(100 - (len(wrong_rows_dynamic) * 100 / self.fairset.shape[0]), 2)

            json_dynamic = {
                "Type": "Dynamic Piping Single-to-Single",
                "Description": f"Block Single-to-Single ({col1} to {col2})",
                "is_valid": True if violations.empty else False,
                "is_supported": is_supported,
                "Dataframe": violations.to_dict(orient="records") if not violations.empty else None,
                "Detail": detail,
                "Occurrences_train": len(train[train[col1].isin(violations[col1].unique())]),
                "Percentage_of_valid_rows": valid_rows_dynamic,
                "Rows": wrong_rows_dynamic,
            }
            return json_dynamic
        else:
            # Group by col1 and check if all corresponding values in col2 are NaN
            nan_triggers = train.groupby(col1, dropna = False)[col2].apply(lambda x: x.isna().all())
            anti_nan_triggers = train.groupby(col1, dropna = False)[col2].apply(
                lambda x: ~x.isna().any())  # values that never lead to nans for force

            # Step 2: Only keep values that are always NaN triggers
            block_triggers = nan_triggers[nan_triggers].index.values  # Only values that map exclusively to NaN
            force_triggers = nan_triggers[anti_nan_triggers].index.values  # Only values that map exclusively to NaN

            # Step 3: Find violations where fairset[col1] is a known trigger but has non-NaN col2 values
            block_mask = (fairset[col1].isin(block_triggers).fillna(False)) & (fairset[col2].notna().fillna(False))
            block_violations = fairset[block_mask][[col1, col2]]

            # Step 4: Find force violations (values that are not triggers but unexpectedly lead to NaN)
            force_mask = fairset[col1].isin(force_triggers).fillna(False)
            force_violations = fairset[force_mask.astype(bool) & fairset[col2].isna().astype(bool)][[col1, col2]]

        wrong_rows_block = block_violations.index.tolist()
        wrong_rows_force = force_violations.index.tolist()

        self.wrong_rows.update(wrong_rows_block)
        self.wrong_rows.update(wrong_rows_force)

        valid_rows_block = round(100 - (len(wrong_rows_block) * 100 / self.fairset.shape[0]), 2)
        valid_rows_force = round(100 - (len(wrong_rows_force) * 100 / self.fairset.shape[0]), 2)

        json_block = {
            "Type": "Block Single-to-Single",
            "Description": f"Block Single-to-Single ({col1} to {col2})",
            "is_valid": True if block_violations.empty else False,
            "is_supported": is_supported,
            "Dataframe": block_violations.to_dict(orient="records") if not block_violations.empty else None,
            "Detail": detail,
            "Occurrences_train": len(train[train[col1].isin(block_violations[col1].unique())]),
            "Percentage_of_valid_rows": valid_rows_block,
            "Rows": wrong_rows_block,
        }
        json_force = {
            "Type": "Force Single-to-Single",
            "Description": f"Force Single-to-Single ({col1} to {col2})",
            "is_valid": True if force_violations.empty else False,
            "is_supported": is_supported,
            "Dataframe": force_violations.to_dict(orient="records") if not force_violations.empty else None,
            "Detail": detail,
            "Occurrences_train": len(train[train[col1].isin(force_violations[col1].unique())]),
            "Percentage_of_valid_rows": valid_rows_force,
            "Rows": wrong_rows_force,
        }
        if block_force == "block":
            return json_block
        elif block_force == "force":
            return json_force


    def detect_violations_SM(self, single_column, prefix, detail, block_force, is_supported=True):

        train = self.train.copy()
        fairset = self.fairset.copy()

        if not isinstance(prefix, list):
            group_col = [col for col in train.columns if col.startswith(prefix) and not col.endswith("oe")]
        else:
            group_col = prefix

        nan_trigers = (
            train.replace("nan", np.nan)
            .groupby(single_column, dropna=False)
            .apply(lambda group: group[group_col].isna().all(axis=1).all())
            .loc[lambda x: x == True]
        )
        anti_nan_triggers = (
            train.replace("nan", np.nan)
            .groupby(single_column, dropna=False)
            .apply(lambda group: ~group[group_col].isna().all(axis=1).any())
            .loc[lambda x: x == True]
        )

        nan_trigers = nan_trigers.index.to_list()
        anti_nan_triggers = anti_nan_triggers.index.to_list()

        violations = fairset[fairset[single_column].isin(nan_trigers)]
        violations = violations[violations[group_col].notna().any(axis=1)][[single_column] + group_col]

        force_violations = fairset[fairset[single_column].isin(anti_nan_triggers)]
        force_violations = force_violations[force_violations[group_col].isna().all(axis=1)][[single_column] + group_col]

        block_violations = violations[~violations[group_col].isna().all(axis=1)]
        wrong_rows_block = block_violations.index.tolist()
        wrong_rows_force = force_violations.index.tolist()

        valid_rows_block = round(100 - (len(wrong_rows_block) * 100 / self.fairset.shape[0]), 2)
        valid_rows_force = round(100 - (len(wrong_rows_force) * 100 / self.fairset.shape[0]), 2)

        self.wrong_rows.update(wrong_rows_block)
        self.wrong_rows.update(wrong_rows_force)

        json_block = {
            "Type": "Block Single-to-Multi",
            "Description": f"Block Single-to-Multi ({single_column} to {prefix})",
            "is_valid": True if block_violations.empty else False,
            "is_supported": is_supported,
            "Dataframe": block_violations.to_dict(orient="records") if not block_violations.empty else None,
            "Detail": detail,
            "Occurrences_train": len(train[train[single_column].isin(nan_trigers)]),
            "Percentage_of_valid_rows": valid_rows_block,
            "Rows": wrong_rows_block,
        }
        json_force = {
            "Type": "Force Single-to-Multi",
            "Description": f"Force Single-to-Multi ({single_column} to {prefix})",
            "is_valid": True if force_violations.empty else False,
            "is_supported": is_supported,
            "Dataframe": force_violations.to_dict(orient="records") if not force_violations.empty else None,
            "Detail": detail,
            "Occurrences_train": len(train[train[single_column].isin(nan_trigers)]),
            "Percentage_of_valid_rows": valid_rows_force,
            "Rows": wrong_rows_force,
        }

        if block_force == "block":
            return json_block
        elif block_force == "force":
            return json_force


    def detect_violations_SM_for_grid(
            self, prefix_single, prefix_multi, c_value, detail, block_force, is_supported=True
    ):
        train = self.train.copy()
        fairset = self.fairset.copy()

        pattern = rf"^{prefix_multi}.*c{c_value}$"
        group_col = [col for col in train.columns if pd.Series(col).str.contains(pattern).any()]
        single_column = prefix_single + str(c_value)

        train = train.replace("nan", np.nan)
        fairset = fairset.replace("nan", np.nan)

        # Identify nan_triggers: conditions where all group columns are NaN in train
        nan_trigers = (
            train.groupby(single_column)
            .apply(lambda group: group[group_col].isna().all(axis=1).all())
            .loc[lambda x: x == True]
        )

        # Convert nan_triggers to a list
        nan_trigers = nan_trigers.index.to_list()

        # Handle cases where single_column itself is NaN
        if train[single_column].isna().any():
            nan_trigers.append(np.nan)

        # Find violations in fairset
        violations = fairset[fairset[single_column].isin(nan_trigers)]

        # Check for non-NaN values in group_col
        violations = violations[violations[group_col].notna().any(axis=1)][[single_column] + group_col]

        block_violations = violations[~violations[group_col].isna().all(axis=1)]
        force_violations = violations[violations[group_col].isna().all(axis=1)]

        wrong_rows_block = block_violations.index.tolist()
        wrong_rows_force = force_violations.index.tolist()

        valid_rows_block = round(100 - (len(wrong_rows_block) * 100 / fairset.shape[0]), 2)
        valid_rows_force = round(100 - (len(wrong_rows_force) * 100 / fairset.shape[0]), 2)

        self.wrong_rows.update(wrong_rows_block)
        self.wrong_rows.update(wrong_rows_force)

        json_block = {
            "Type": "Block Single-to-Multi",
            "Description": f"Block Single-to-Multi Grid ({single_column} to {prefix_multi})",
            "is_valid": True if block_violations.empty else False,
            "is_supported": is_supported,
            "Dataframe": block_violations.to_dict(orient="records") if not block_violations.empty else None,
            "Detail": detail,
            "Occurrences_train": len(train[train[single_column].isin(nan_trigers)]),
            "Percentage_of_valid_rows": valid_rows_block,
            "Rows": wrong_rows_block,
        }

        json_force = {
            "Type": "Force Single-to-Multi",
            "Description": f"Force Single-to-Multi Grid ({single_column} to {prefix_multi})",
            "is_valid": True if force_violations.empty else False,
            "is_supported": is_supported,
            "Dataframe": force_violations.to_dict(orient="records") if not force_violations.empty else None,
            "Detail": detail,
            "Occurrences_train": len(train[train[single_column].isin(nan_trigers)]),
            "Percentage_of_valid_rows": valid_rows_force,
            "Rows": wrong_rows_force,
        }

        if block_force == "block":
            return json_block
        elif block_force == "force":
            return json_force


    def detect_violations_MM(self, prefix1, prefix2, columns_to_drop, detail, block_force, is_supported=True):

        train = self.train.copy()
        fairset = self.fairset.copy()

        if columns_to_drop:
            train = train.drop(columns_to_drop, axis=1)
            fairset = fairset.drop(columns_to_drop, axis=1)

        # Step 1: Identify columns that start with the given prefixes in both train and fairset
        if not isinstance(prefix1, list):
            cols_prefix1_train = [col for col in train.columns if col.startswith(prefix1) and not col.endswith("oe")]
            cols_prefix1_fairset = [col for col in fairset.columns if
                                    col.startswith(prefix1) and not col.endswith("oe")]
        else:
            cols_prefix1_train = prefix1
            cols_prefix1_fairset = prefix1

        if not isinstance(prefix2, list):
            cols_prefix2_train = [col for col in train.columns if col.startswith(prefix2) and not col.endswith("oe")]
            cols_prefix2_fairset = [col for col in fairset.columns if
                                    col.startswith(prefix2) and not col.endswith("oe")]
        else:
            cols_prefix2_train = prefix2
            cols_prefix2_fairset = prefix2

        # Check if both prefixes have the same number of columns in train and fairset
        if len(cols_prefix1_train) != len(cols_prefix2_train) or len(cols_prefix1_fairset) != len(cols_prefix2_fairset):
            return {
                "Type": "Block Multi-to-Multi",
                "Description": f"Number of columns mismatch between {prefix1} and {prefix2}.",
                "is_valid": False,
                "Dataframe": None,
                "Detailed_Violations": [],
                "Rows": []
            }

        # Initialize an empty DataFrame to store all violations
        all_violations = pd.DataFrame()
        block_violations = pd.DataFrame()
        force_violations = pd.DataFrame()
        detailed_violations_block = []
        detailed_violations_force = []  # List to store detailed violation descriptions for each pair

        # Step 2: For each pair of columns, check if a value in prefix1 always leads to "nan" in prefix2 in train
        for col1_train, col2_train, col1_fairset, col2_fairset in zip(
                cols_prefix1_train, cols_prefix2_train, cols_prefix1_fairset, cols_prefix2_fairset
        ):
            # Extract unique values from the prefix1 column in the train set
            unique_values = train[col1_train].dropna().unique()

            forcing_rules = []  # Store values that force "nan" in prefix2
            forcing_answer_rules = []  # Store values that force non-nan answers in prefix2
            # Step 3: Identify values that always force "nan" in prefix2 in train
            for val in unique_values:
                # Check if the value in col1_train always leads to "nan" in col2_train
                condition_train = train[col1_train] == val
                if (train[condition_train][col2_train].isna()).all():  # All values are "nan" in prefix2
                    forcing_rules.append(val)
                elif (train[condition_train][col2_train].isna()).any():
                    json_train_failure = {
                        "Type": "Parallel Piping",
                        "Description": f"Parallel Piping ({col1_train} to {col2_train}) does not uphold in the trainset",
                        "is_valid": True,
                        "is_supported": is_supported,
                        "Dataframe": None,
                        "Detailed_Violations": None,
                        "Detail": "Failure in the trainset",
                        "Percentage_of_valid_rows": 100,
                        "Rows": [],
                    }
                    return json_train_failure
                else:
                    forcing_answer_rules.append(val)
            # If no forcing rules are found, skip to the next pair
            if not forcing_rules:
                continue

            # Step 4: Check the same rules in the fairset
            for val in forcing_rules:
                condition_fairset = fairset[col1_fairset] == val
                violations_fairset = fairset[condition_fairset & (fairset[col2_fairset].notna())][
                    cols_prefix1_fairset + cols_prefix2_fairset
                    ]  # Non-"nan" values

                if not violations_fairset.empty:  # If there are violations in the fairset
                    # Add these violations to the combined violations DataFrame
                    block_violations = pd.concat([block_violations, violations_fairset])
                    # Create a detailed explanation for the violation
                    detailed_violations_block.append(
                        {
                            "Violation_Col1": col1_fairset,
                            "Violation_Col2": col2_fairset,
                            "Forcing_Values": forcing_rules,
                            "Description": f"Forcing values in '{col1_fairset}' should force 'NaN' in '{col2_fairset}', but {len(violations_fairset)} violations were found.",
                            "Violation_Dataframe": violations_fairset[[col1_fairset, col2_fairset]].to_dict(
                                orient="records"
                            ),
                        }
                    )

            for val in forcing_answer_rules:
                condition_fairset = fairset[col1_fairset] == val
                violations_fairset = fairset[condition_fairset & (fairset[col2_fairset].isna())][
                    cols_prefix1_fairset + cols_prefix2_fairset
                    ]  # "nan" values

                if not violations_fairset.empty:  # If there are violations in the fairset
                    # Add these violations to the combined violations DataFrame
                    force_violations = pd.concat([force_violations, violations_fairset])

                    # Create a detailed explanation for the violation
                    detailed_violations_force.append(
                        {
                            "Violation_Col1": col1_fairset,
                            "Violation_Col2": col2_fairset,
                            "Forcing_Values": forcing_answer_rules,
                            "Description": f"Forcing values in '{col1_fairset}' should force non NaN values in '{col2_fairset}', but {len(violations_fairset)} violations were found.",
                            "Violation_Dataframe": violations_fairset[[col1_fairset, col2_fairset]].to_dict(
                                orient="records"
                            ),
                        }
                    )

        # Adding the wrong rows for stats
        self.wrong_rows.update(block_violations.index.tolist())
        self.wrong_rows.update(force_violations.index.tolist())

        wrong_rows_block = block_violations.index.tolist()
        wrong_rows_force = force_violations.index.tolist()

        valid_rows_block = round(100 - (len(wrong_rows_block) * 100 / self.fairset.shape[0]), 2)
        valid_rows_force = round(100 - (len(wrong_rows_force) * 100 / self.fairset.shape[0]), 2)

        # Step 5: Create the JSON structure
        json_block = {
            "Type": "Parallel Piping",
            "Description": f"Block Multi-to-Multi ({prefix1} to {prefix2})",
            "is_valid": True if block_violations.empty else False,
            "is_supported": is_supported,
            "Dataframe": block_violations.to_dict(orient="records") if not block_violations.empty else None,
            "Detailed_Violations": detailed_violations_block,
            "Detail": detail,
            "Percentage_of_valid_rows": valid_rows_block,
            "Rows": wrong_rows_block,
        }

        json_force = {
            "Type": "Parallel Piping",
            "Description": f"Force Multi-to-Multi ({prefix1} to {prefix2})",
            "is_valid": True if force_violations.empty else False,
            "is_supported": is_supported,
            "Dataframe": force_violations.to_dict(orient="records") if not force_violations.empty else None,
            "Detailed_Violations": detailed_violations_force,
            "Detail": detail,
            "Percentage_of_valid_rows": valid_rows_force,
            "Rows": wrong_rows_force,
        }
        if block_force == "block":
            return json_block
        elif block_force == "force":
            return json_force


    def detect_violations_MS(self, single_column, prefix, detail, is_supported=True):
        train = self.train.copy()
        fairset = self.fairset.copy()

        # Identify group columns based on the prefix and exclude columns ending with 'oe'
        group_col = [col for col in train.columns if col.startswith(prefix) and not col.endswith("oe")]

        # Add the single column to the group columns list
        group_col.append(single_column)

        # Get unique combinations of group columns in both train and fairset datasets
        train_combinations = train[group_col].drop_duplicates().reset_index(drop=True)
        fairset_combinations = fairset[group_col].drop_duplicates().reset_index(drop=True)

        # Identify combinations that are in fairset but not in train
        missing_combinations = fairset_combinations.merge(train_combinations, on=group_col, how="left", indicator=True)
        missing_combinations = missing_combinations[missing_combinations["_merge"] == "left_only"].drop(
            columns=["_merge"]
        )

        # Save indexes of missing combinations in the fairset
        missing_indexes = fairset.merge(missing_combinations, on=group_col, how="inner").index.tolist()
        valid_rows = round(100 - (len(missing_indexes) * 100 / self.fairset.shape[0]), 2)

        self.wrong_rows.update(missing_indexes)

        # Create the JSON structure to return
        json = {
            "Type": "Block Multi-to-Single",
            "Description": f"Missing Combinations for {single_column} to {prefix}",
            "is_valid": True if missing_combinations.empty else False,
            "is_supported": is_supported,
            "Dataframe": missing_combinations.to_dict(orient="records") if not missing_combinations.empty else None,
            "Indexes": missing_indexes if missing_indexes else None,
            "Detail": detail,
            "Percentage_of_valid_rows": valid_rows,
            "Rows": missing_indexes,
        }

        return json


    def detect_violations_MS_v2(self, single_column, prefix, detail, block_force, is_supported=True):
        train = self.train.copy()
        fairset = self.fairset.copy()

        # Identify group columns based on the prefix and exclude columns ending with 'oe'
        if not isinstance(prefix, list):
            group_col = [col for col in train.columns if col.startswith(prefix) and not col.endswith("oe")]
        else:
            group_col = prefix
        filtered_df_block = train[group_col + [single_column]].query(f"`{single_column}`.isnull()")

        unique_groups = filtered_df_block[group_col].drop_duplicates()
        group_combinations = list(unique_groups.itertuples(index=False, name=None))
        mask = fairset[group_col].apply(tuple, axis=1).isin(group_combinations)

        block_violations = fairset[mask & fairset[single_column].notna()][group_col + [single_column]]
        wrong_rows_block = block_violations.index.tolist()

        filtered_df_force = train[group_col + [single_column]].query(f"`{single_column}`.notnull()")
        unique_groups_force = filtered_df_force[group_col].drop_duplicates()
        group_combinations_force = list(unique_groups_force.itertuples(index=False, name=None))

        mask_force = fairset[group_col].apply(tuple, axis=1).isin(group_combinations_force)
        force_violations = fairset[mask_force & fairset[single_column].isna()][group_col + [single_column]]
        wrong_rows_force = force_violations.index.tolist()

        valid_rows_block = round(100 - (len(wrong_rows_block) * 100 / self.fairset.shape[0]), 2)
        valid_rows_force = round(100 - (len(wrong_rows_force) * 100 / self.fairset.shape[0]), 2)

        self.wrong_rows.update(wrong_rows_block)
        self.wrong_rows.update(wrong_rows_force)

        json_block = {
            "Type": "Block Multi-to-Single",
            "Description": f"Block Multi-to-Single ({single_column} to {prefix})",
            "is_valid": True if block_violations.empty else False,
            "is_supported": is_supported,
            "Dataframe": block_violations.to_dict(orient="records") if not block_violations.empty else None,
            "Detail": detail,
            "Occurrences_train": len(train[train[group_col].apply(tuple, axis=1).isin(group_combinations)]),
            "Percentage_of_valid_rows": valid_rows_block,
            "Rows": wrong_rows_block,
        }

        json_force = {
            "Type": "Force Multi-to-Single",
            "Description": f"Force Multi-to-Single ({single_column} to {prefix})",
            "is_valid": True if force_violations.empty else False,
            "is_supported": is_supported,
            "Dataframe": force_violations.to_dict(orient="records") if not force_violations.empty else None,
            "Detail": detail,
            "Occurrences_train": len(train[train[group_col].apply(tuple, axis=1).isin(group_combinations_force)]),
            "Percentage_of_valid_rows": valid_rows_force,
            "Rows": wrong_rows_force,
        }

        if block_force == "block":
            return json_block
        elif block_force == "force":
            return json_force


    def detect_bf_mixed_type(self, prefix1, prefix2, columns_to_drop, detail, is_supported=False):
        """
        Checks that for every matching (row, col) in subset1 and subset2:
        If subset1[row, col] == 0, then subset2[row, col] must be 0 or NaN.

        Returns a JSON-like dictionary with a summary and detailed breakdown of violations.
        """
        # Convert DataFrames to NumPy arrays for positional comparison
        train = self.train.copy()
        fairset = self.fairset.copy()

        if columns_to_drop:
            train = train.drop(columns_to_drop, axis=1)
            fairset = fairset.drop(columns_to_drop, axis=1)

        # Step 1: Identify columns that start with the given prefixes in both train and fairset
        subset1_cols = [col for col in fairset.columns if col.startswith(prefix1) and not col.endswith("oe")]
        subset2_cols = [col for col in fairset.columns if col.startswith(prefix2) and not col.endswith("oe")]

        subset1 = fairset[[col for col in fairset.columns if col.startswith(prefix1) and not col.endswith("oe")]]
        subset2 = fairset[[col for col in fairset.columns if col.startswith(prefix2) and not col.endswith("oe")]]

        # Check if both prefixes have the same number of columns in train and fairset
        subset1_array = subset1.to_numpy()
        subset2_array = subset2.to_numpy()

        # Ensure both arrays have the same shape
        if subset1_array.shape != subset2_array.shape:
            return {
                "Type": "Block Multi-to-Multi (mixed values)",
                "Description": f"Mismatch in shapes between {prefix1} and {prefix2}.",
                "is_valid": False,
                "Dataframe": None,
                "Detailed_Violations": [],
                "Percent of valid rows": 100,
            }

        # Create a boolean mask where subset1 is 0 but subset2 is not 0 or NaN
        mask = (subset1_array == 0) & ~((subset2_array == 0) | np.isnan(subset2_array))

        # Get row and column indices of violations
        row_idx, col_idx = np.where(mask)

        # Create DataFrame of violations
        # Get the indices of violating rows in the original DataFrame
        violating_indices = subset1.index[row_idx]

        # Create a DataFrame containing only the violating rows
        violations_df = fairset.loc[violating_indices, subset1_cols + subset2_cols]

        valid_rows = round(100 - (len(violating_indices) * 100 / self.fairset.shape[0]), 2)

        # Construct JSON-like response
        result = {
            "Type": "Block Multi-to-Multi (mixed values)",
            "Description": f"Block Multi-to-Multi  {prefix1} == 0 but {prefix2} is not 0 or NaN.",
            "is_valid": True if violations_df.empty else False,
            "Dataframe": violations_df.to_dict(orient="records") if not violations_df.empty else None,
            "Detail": detail,
            "Percentage_of_valid_rows": valid_rows,
            "is_supported": is_supported,
            "Rows": violating_indices.tolist(),
        }

        return result


    def recoding(self, prefix1, prefix2, mode, detail, is_supported=True):

        train = self.train.copy()
        fairset = self.fairset.copy()

        # Normalize single-element lists to scalars (priorFile may pass ['A03'] from "['A03']" in CSV)
        if isinstance(prefix1, list) and len(prefix1) == 1:
            prefix1 = prefix1[0]
        if isinstance(prefix2, list) and len(prefix2) == 1:
            prefix2 = prefix2[0]

        if mode == "SS":
            valid_combinations = set(train[[prefix1, prefix2]].drop_duplicates().itertuples(index=False, name=None))

            # Find all violating rows from the fairset
            violations = fairset[~fairset[[prefix1, prefix2]].apply(tuple, axis=1).isin(valid_combinations)][
                [prefix1, prefix2]
            ]

            # Adding the wrong rows for stats
            self.wrong_rows.update(violations.index.tolist())
            wrong_rows = violations.index.tolist()
            valid_rows = round(100 - (len(wrong_rows) * 100 / self.fairset.shape[0]), 2)

            json = {
                "Type": "Recoding Single-to-Single",
                "Description": f"Recoding Single-to-Single ({prefix1} to {prefix2})",
                "is_valid": True if violations.empty else False,
                "is_supported": is_supported,
                "Dataframe": violations.to_dict(orient="records") if not violations.empty else None,
                "Detail": detail,
                "Percentage_of_valid_rows": valid_rows,
                "Rows": wrong_rows,
            }
            return json

        elif mode == "SM":
            if not isinstance(prefix2, list):
                cols = [col for col in train.columns if col.startswith(prefix2) and not col.endswith("oe")]
            else:
                cols = prefix2

            # Find valid combinations from train (Real data)
            df_subset = train[[prefix1] + cols].drop_duplicates()

            # Convert any list values in rows to tuples
            valid_combinations = set(
                tuple(tuple(x) if isinstance(x, list) else x for x in row)
                for row in df_subset.itertuples(index=False, name=None)
            )


            # Find all violating rows from the fairset
            violations = fairset[~fairset[[prefix1] + cols].apply(tuple, axis=1).isin(valid_combinations)][
                [prefix1] + cols
                ]

            # Adding the wrong rows for stats
            self.wrong_rows.update(violations.index.tolist())
            wrong_rows = violations.index.tolist()
            valid_rows = round(100 - (len(wrong_rows) * 100 / self.fairset.shape[0]), 2)

            json = {
                "Type": "Recoding Single-to-Multi",
                "Description": f"Recoding Single-to-Multi ({prefix1} to {prefix2})",
                "is_valid": True if violations.empty else False,
                "is_supported": is_supported,
                "Dataframe": violations.to_dict(orient="records") if not violations.empty else None,
                "Detail": detail,
                "Percentage_of_valid_rows": valid_rows,
                "Rows": wrong_rows,
            }
            return json

        elif mode == "MS":
            if not isinstance(prefix1, list):
                cols = [col for col in train.columns if col.startswith(prefix1) and not col.endswith("oe")]
            else:
                cols = prefix1
            # combinations of just the source
            valid_source_combinations = set(train[cols].drop_duplicates().itertuples(index=False, name=None))
            # Find valid combinations from train (Real data)
            valid_source_target_combinations = set(
                train[[prefix2] + cols].drop_duplicates().itertuples(index=False, name=None))
            # Find combinations generated by fairgen in the source columns
            new_combinations = fairset[~fairset[cols].apply(tuple, axis=1).isin(valid_source_combinations)][
                cols].index

            fairset_not_new_combinations = fairset.drop(index=new_combinations)

            # Find all violating rows from the fairset
            violations = fairset_not_new_combinations[
                ~fairset_not_new_combinations[[prefix2] + cols].apply(tuple, axis=1).isin(
                    valid_source_target_combinations)][
                [prefix2] + cols
                ]

            # Adding the wrong rows for stats
            self.wrong_rows.update(violations.index.tolist())
            wrong_rows = violations.index.tolist()
            valid_rows = round(100 - (len(wrong_rows) * 100 / self.fairset.shape[0]), 2)

            json = {
                "Type": "Recoding Multi-to-Single",
                "Description": f"Recoding Multi-to-Single ({prefix1} to {prefix2})",
                "is_valid": True if violations.empty else False,
                "is_supported": is_supported,
                "Dataframe": violations.to_dict(orient="records") if not violations.empty else None,
                "Detail": detail,
                "Percentage_of_valid_rows": valid_rows,
                "Rows": wrong_rows,
            }
            return json

        elif mode == "MM":
            if not isinstance(prefix1, list):
                cols1 = [col for col in train.columns if col.startswith(prefix1) and not col.endswith("oe")]
            else:
                cols1 = prefix1
            if not isinstance(prefix2, list):
                cols2 = [col for col in train.columns if col.startswith(prefix2) and not col.endswith("oe")]
            else:
                cols2 = prefix2

            # Find valid combinations from train (Real data)
            valid_combinations = set(train[cols1 + cols2].drop_duplicates().itertuples(index=False, name=None))

            # Find all violating rows from the fairset
            violations = fairset[~fairset[cols1 + cols2].apply(tuple, axis=1).isin(valid_combinations)][cols1 + cols2]

            # Adding the wrong rows for stats
            self.wrong_rows.update(violations.index.tolist())
            wrong_rows = violations.index.tolist()
            valid_rows = round(100 - (len(wrong_rows) * 100 / self.fairset.shape[0]), 2)

            json = {
                "Type": "Recoding Multi-to-Multi",
                "Description": f"Recoding Multi-to-Multi ({prefix1} to {prefix2})",
                "is_valid": True if violations.empty else False,
                "is_supported": is_supported,
                "Dataframe": violations.to_dict(orient="records") if not violations.empty else None,
                "Detail": detail,
                "Percentage_of_valid_rows": valid_rows,
                "Rows": wrong_rows,
            }
            return json


    def none_of_the_above(self, prefix, nota, columns_to_drop, is_supported=True):
        train = self.train.copy()
        fairset = self.fairset.copy()

        if columns_to_drop:
            train = train.drop(columns_to_drop, axis=1)
            fairset = fairset.drop(columns_to_drop, axis=1)
        if not isinstance(prefix, list) and isinstance(prefix, str):
            cols = [col for col in train.columns if col.startswith(prefix) and not col.endswith("oe")]
        else:
            cols = prefix

        if nota in cols:
            cols.remove(nota)

        train = train.dropna(subset=cols + [nota], how="all", axis=0)
        fairset = fairset.dropna(subset=cols + [nota], how="all", axis=0)

        train_violations = train[
            (train[nota].astype(str).apply(lambda x: not x.lower().startswith(("no", "0", "non"))))
            & (
                ~train[cols]
                .astype(str)  # <-- Add this
                .map(lambda x: x.lower().startswith(("no", "0", "non")) or x in ["", " ", "nan"])
                .all(axis=1)
            )
            ][cols + [nota]]

        if train_violations.empty and not train.empty:
            fairset_violations = fairset[
                (fairset[nota].astype(str).apply(lambda x: not x.lower().startswith(("no", "0", "non"))))
                & (
                    ~fairset[cols]
                    .astype(str)  # <-- Add this
                    .map(lambda x: x.lower().startswith(("no", "0", "non")) or x in ["", " ", "nan"])
                    .all(axis=1)
                )
                ][cols + [nota]]

            # Adding the wrong rows for stats
            self.wrong_rows.update(fairset_violations.index.tolist())
            wrong_rows = fairset_violations.index.tolist()
            valid_rows = round(100 - (len(wrong_rows) * 100 / self.fairset.shape[0]), 2)

        else:
            fairset_violations = pd.DataFrame()
            valid_rows = 100
            wrong_rows = []
        json = {
            "Type": "None of the Above",
            "Description": f"None of the Above ({prefix})" if train_violations.empty else "Training Data not Reliable",
            "is_valid": True if ((not train_violations.empty) | (fairset_violations.empty)) else False,
            "is_supported": is_supported,
            "Dataframe": fairset_violations.to_dict(orient="records") if not fairset_violations.empty else None,
            "Percentage_of_valid_rows": valid_rows,
            "Rows": wrong_rows,
        }
        return json


    def none_of_the_above_grid(self, prefix, nota, columns_to_drop, c_value, is_supported=True):
        train = self.train.copy()
        fairset = self.fairset.copy()

        if columns_to_drop:
            train = train.drop(columns_to_drop, axis=1)
            fairset = fairset.drop(columns_to_drop, axis=1)

        pattern = rf"^{prefix}.*c{c_value}$"
        cols = [col for col in train.columns if pd.Series(col).str.contains(pattern).any()]

        if not isinstance(prefix, list) and isinstance(prefix, str):
            cols = [
                col for col in train.columns if pd.Series(col).str.contains(pattern).any() and not col.endswith("oe")
            ]
        else:
            cols = prefix

        if nota in cols:
            cols.remove(nota)

        train = train.dropna(subset=cols + [nota], how="all", axis=0)
        fairset = fairset.dropna(subset=cols + [nota], how="all", axis=0)

        train_violations = train[
            (train[nota].astype(str).apply(lambda x: not x.lower().startswith(("no", "0"))))
            & (
                ~train[cols]
                .map(
                    lambda x: (
                        np.isnan(x) if isinstance(x, float) and x != 0.0 else str(x).lower().startswith(("no", "0"))
                    )
                )
                .all(axis=1)
            )
            ][cols + [nota]]

        if train_violations.empty:
            fairset_violations = fairset[
                (fairset[nota].astype(str).apply(lambda x: not x.lower().startswith(("no", "0"))))
                & (
                    ~fairset[cols]
                    .map(
                        lambda x: (
                            np.isnan(x) if isinstance(x, float) and x != 0.0 else str(x).lower().startswith(("no", "0"))
                        )
                    )
                    .all(axis=1)
                )
                ][cols + [nota]]

            # Adding the wrong rows for stats
            self.wrong_rows.update(fairset_violations.index.tolist())
            wrong_rows = fairset_violations.index.tolist()
            valid_rows = round(100 - (len(wrong_rows) * 100 / self.fairset.shape[0]), 2)

        else:
            fairset_violations = pd.DataFrame()
            valid_rows = 100
            wrong_rows = []
        json = {
            "Type": "None of the Above",
            "Description": f"None of the Above ({prefix})" if train_violations.empty else "Training Data not Reliable",
            "is_valid": True if ((not train_violations.empty) | (fairset_violations.empty)) else False,
            "is_supported": is_supported,
            "Dataframe": fairset_violations.to_dict(orient="records") if not fairset_violations.empty else None,
            "Percentage_of_valid_rows": valid_rows,
            "Rows": wrong_rows,
        }
        return json


    def all_of_the_above(self, prefix, aota, columns_to_drop, is_supported=True):
        train = self.train.copy()
        fairset = self.fairset.copy()

        if columns_to_drop:
            train = train.drop(columns_to_drop, axis=1)
            fairset = fairset.drop(columns_to_drop, axis=1)

        # Identify columns with the given prefix
        if not isinstance(prefix, list) and isinstance(prefix, str):
            cols = [col for col in train.columns if col.startswith(prefix) and not col.endswith("oe")]
        else:
            cols = prefix

        if aota in cols:
            cols.remove(aota)

        # Filter out rows where all columns (including aota) are NaN
        train = train[cols + [aota]].dropna(how="all")
        fairset = fairset[cols + [aota]].dropna(how="all")

        train_violations = train[
            (
                    train[aota]
                    .astype(str)
                    .apply(lambda x: not x.lower().startswith(("no", "0")) and not str(x) in ["", " ", "nan"])
                    & train[aota].notna()
            )
            & (
                ~train[cols]
                .map(
                    lambda x: (
                        np.isnan(x)
                        if isinstance(x, float)
                        else str(x).lower().startswith(("no", "0")) or str(x) in ["", " ", "nan"]
                    )
                )
                .all(axis=1)
            )
            ][cols + [aota]]

        if train_violations.empty:
            fairset_violations = fairset[
                (
                        fairset[aota].astype(str).apply(lambda x: not x.lower().startswith(("no", "0")))
                        & fairset[aota].notna()
                )
                & (
                    ~fairset[cols]
                    .map(lambda x: np.isnan(x) if isinstance(x, float) else str(x).lower().startswith(("no", "0")))
                    .all(axis=1)
                )
                ][cols + [aota]]

            # Adding the wrong rows for stats
            self.wrong_rows.update(fairset_violations.index.tolist())
            wrong_rows = fairset_violations.index.tolist()
            valid_rows = round(100 - (len(wrong_rows) * 100 / self.fairset.shape[0]), 2)

        else:
            valid_rows = 100
            fairset_violations = pd.DataFrame()
            wrong_rows = []

        json = {
            "Type": "All of the Above",
            "Description": f"All of the Above ({prefix})" if train_violations.empty else "Training Data not Reliable",
            "is_valid": True if ((not train_violations.empty) | (fairset_violations.empty)) else False,
            "is_supported": is_supported,
            "Dataframe": fairset_violations.to_dict(orient="records") if not fairset_violations.empty else None,
            "Percentage_of_valid_rows": valid_rows,
            "Rows": wrong_rows,
        }
        return json


    def count(self, prefix, none_of_the_above, is_supported=True):
        train = self.train.copy()
        fairset = self.fairset.copy()

        if not isinstance(prefix, list) and isinstance(prefix, str):
            columns = [col for col in train.columns if col.startswith(prefix)]
        else:
            columns = prefix
        # Remove all NaNs and keep only relevant columns
        train = train[columns].dropna(how="all")
        fairset = fairset[columns].dropna(how="all")

        # Remove rows where all values in the columns start with "no"
        train_cleaned = train[
            ~train[columns].apply(
                lambda row: all(str(x).strip().lower().startswith("no") for x in row if pd.notna(x)), axis=1
            )
        ]
        if none_of_the_above is not None:
            # Ensure it's a list of column names
            if isinstance(none_of_the_above, str):
                none_of_the_above = [none_of_the_above]
            elif not isinstance(none_of_the_above, list):
                # It's probably float('nan'), None, etc.
                none_of_the_above = []

            def should_drop(row):
                for col in none_of_the_above:
                    val = row.get(col)
                    if pd.notna(val) and str(val).lower().startswith(("no ", "0")):
                        return True
                return False

            train_cleaned = train_cleaned[~train_cleaned.apply(should_drop, axis=1)]
            fairset = fairset[~fairset.apply(should_drop, axis=1)]

        # Count the number of valid answers directly for train
        train_valid_counts = train_cleaned.apply(
            lambda row: sum(
                str(x).strip().lower() not in ["", "nan"] and not str(x).strip().lower().startswith(("no", "0"))
                for x in row
            ),
            axis=1,
        )

        # Get the min and max valid answers in the train set
        min_answers, max_answers = train_valid_counts.min(), train_valid_counts.max()

        # Count the number of valid answers directly for fairset
        fairset_valid_counts = fairset.apply(
            lambda row: sum(
                str(x).strip().lower() not in ["", "nan"] and not str(x).strip().lower().startswith(("no", "0"))
                for x in row
            ),
            axis=1,
        )

        # Identify violations in fairset
        fairset_violations = fairset[(fairset_valid_counts < min_answers) | (fairset_valid_counts > max_answers)]

        # Adding the wrong rows for stats
        self.wrong_rows.update(fairset_violations.index.tolist())
        wrong_rows = fairset_violations.index.tolist()
        valid_rows = round(100 - (len(wrong_rows) * 100 / self.fairset.shape[0]), 2)

        # Create the JSON structure
        json = {
            "Type": "Count",
            "Description": f"Count - ({prefix}) (Min answers expected: {min_answers}, Max answers expected: {max_answers})",
            "is_valid": True if fairset_violations.empty else False,
            "is_supported": is_supported,
            "Dataframe": fairset_violations.to_dict(orient="records") if not fairset_violations.empty else None,
            "Percentage_of_valid_rows": valid_rows,
            "Rows": wrong_rows,
        }

        return json


    def uniqueness(self, prefix, is_supported=True):
        train = self.train.copy()
        fairset = self.fairset.copy()
        # Get columns with the given prefix
        if not isinstance(prefix, list):
            cols = [col for col in train.columns if col.startswith(prefix)]
        else:
            cols = prefix

        # Check for uniqueness violations in the train set
        train_non_nan_zero = train[cols].apply(lambda x: x.dropna().replace(0, pd.NA), axis=1)
        train_violations = train[train_non_nan_zero.apply(lambda row: row[row.notna()].duplicated().any(), axis=1)]

        # Check for uniqueness violations in the fairset
        fairset_non_nan_zero = fairset[cols].apply(lambda x: x.dropna().replace(0, pd.NA), axis=1)
        fairset_violations = fairset[
            fairset_non_nan_zero.apply(lambda row: row[row.notna()].duplicated().any(), axis=1)
        ]

        # Check that every row in `train[cols]` has all unique values.
        if (train[cols].nunique(axis=1) == len(cols)).all():
            # For each row in `fairset[cols]`, check if `unique_vals` is a subset of that row.
            # Concatenate the resulting boolean Series to `fairset_violations`.
            unique_vals = set(np.unique(train[cols].values))
            invalid_rows = fairset[~fairset[cols].apply(lambda row: unique_vals.issubset(set(row.dropna())), axis=1)]
            fairset_violations = pd.concat([fairset_violations, invalid_rows])

        # Adding the wrong rows for stats
        self.wrong_rows.update(fairset_violations.index.tolist())
        wrong_rows = fairset_violations.index.tolist()
        valid_rows = round(100 - (len(wrong_rows) * 100 / self.fairset.shape[0]), 2)

        # Create the JSON structure to return
        json = {
            "Type": "Uniqueness",
            "Description": f"Uniqueness - ({prefix})" if train_violations.empty else "Training Data not Reliable",
            "is_valid": True if ((not train_violations.empty) | (fairset_violations.empty)) else False,
            "is_supported": is_supported,
            "Dataframe": fairset_violations[cols].to_dict(orient="records") if not fairset_violations.empty else None,
            "Percentage_of_valid_rows": valid_rows,
            "Rows": wrong_rows,
        }
        return json

    @staticmethod
    def applyQueryCustom_query(df, instruction):
        # Force numeric conversion - just use coerce, NaN for non-convertible values
        df = df.apply(lambda col: pd.to_numeric(col, errors='coerce'))
        row_filter, columns = instruction.rsplit(";", 1)
        columns = [col.strip() for col in columns.split(",")]
        return df.query(row_filter, engine="python")[columns]

    @staticmethod
    def applyQueryCustom_freecode(df, instruction):
        # Force numeric conversion for all columns before executing custom code
        # Convert everything to numeric, non-numeric becomes NaN
        df_converted = df.apply(lambda col: pd.to_numeric(col, errors='coerce'))
        
        env = {"df": df_converted, "np": np, "pd": pd}
        try:
            exec(instruction, env)
            if "df_check" not in env or env["df_check"] is None:
                raise ValueError("Instruction did not assign df_check.")
            returned_df = env["df_check"]
            return returned_df
        except Exception as e:
            st.error(f"Error Custom, running instruction: \n{instruction}")
            st.error(f"{type(e).__name__}: {e}")
            st.text(traceback.format_exc())
            return pd.DataFrame()
        

    @staticmethod
    def custom(dataframe, constraint_type, description, fairset, is_supported=True):
        wrong_rows = dataframe.index.tolist()
        valid_rows = round(100 - (len(wrong_rows) * 100 / fairset.shape[0]), 2)  # Adding the wrong rows for stats
        json = {
            "Type": constraint_type,
            "Description": f"{constraint_type} - {description}",
            "Detail": description,
            "is_valid": True if dataframe.empty else False,
            "is_supported": is_supported,
            "Dataframe": dataframe.to_dict(orient="records"),
            "Percentage_of_valid_rows": valid_rows,
            "Rows": wrong_rows,
        }
        return json


    def process_constraint(self, constraint_type, constraint):
        """Handles the logic of constraint checking for each constraint typ"""
        if constraint_type == "BF_SS":
            try:
                resp = self.detect_violations_SS(*constraint)
                return resp
            except Exception as e:
                st.error(f"Issue on constraint BF_SS: {list(constraint)}")
                st.error(f"Error: {e}")
                st.error(traceback.format_exc())
        elif constraint_type == "BF_SM":
            return self.detect_violations_SM(*constraint)
        elif constraint_type == "BF_SM_Grid":
            return self.detect_violations_SM_for_grid(*constraint)
        elif constraint_type == "BF_MM":
            return self.detect_violations_MM(*constraint)
        elif constraint_type == "BF_MS":
            return self.detect_violations_MS_v2(*constraint)
        elif constraint_type == "BF_Mixed_Type":
            return self.detect_bf_mixed_type(*constraint)
        elif constraint_type == "NOTAs":
            return self.none_of_the_above(*constraint)
        elif constraint_type == "NOTAs_grid":
            return self.none_of_the_above_grid(*constraint)
        elif constraint_type == "AOTAs":
            return self.all_of_the_above(*constraint)
        elif constraint_type == "recodings":
            return self.recoding(*constraint)
        elif constraint_type == "count":
            return self.count(*constraint)
        elif constraint_type == "uniqueness":
            return self.uniqueness(*constraint)
        elif constraint_type == "custom_query":
            try:
                constraint_type, description, query, is_implemented = constraint
            except ValueError:
                constraint_type, description, query = constraint

            dataframe = LogicFunctions.applyQueryCustom_query(self.fairset, query)
            if not dataframe.empty:
                self.wrong_rows.update(dataframe.index.tolist())
            result = LogicFunctions.custom(dataframe, constraint_type, description, self.fairset)
            return result
        elif constraint_type == "custom":
            try:
                constraint_type, description, code, is_implemented = constraint
            except ValueError:
                constraint_type, description, code = constraint
                is_implemented = True

            dataframe = LogicFunctions.applyQueryCustom_freecode(self.fairset, code)
            if not dataframe.empty:
                try:
                    self.wrong_rows.update(dataframe.index.tolist())
                except AttributeError:
                    st.write(code)
                    st.write(st.dataframe)
                # self.wrong_rows.update(dataframe.index.tolist())
            result = LogicFunctions.custom(dataframe, constraint_type, description, self.fairset,
                                           is_supported=is_implemented)
            return result
        else:
            raise ValueError(f"Unknown constraint type: {constraint_type}")


    def run_analysis(self, constraints):
        all_results = []

        all_constraints = [
            ("BF_SS", constraints.get("BF_SS", [])),
            ("BF_SM", constraints.get("BF_SM", [])),
            ("BF_SM_Grid", constraints.get("BF_SM_Grid", [])),
            ("BF_MM", constraints.get("BF_MM", [])),
            ("BF_MS", constraints.get("BF_MS", [])),
            ("BF_Mixed_Type", constraints.get("BF_Mixed_Type", [])),
            ("NOTAs", constraints.get("NOTAs", [])),
            ("NOTAs_grid", constraints.get("NOTAs_grid", [])),
            ("AOTAs", constraints.get("AOTAs", [])),
            ("recodings", constraints.get("recodings", [])),
            ("count", constraints.get("count", [])),
            ("uniqueness", constraints.get("uniqueness", [])),
            ("custom_query", constraints.get("custom_query", [])),
            ("custom", constraints.get("custom", [])),
        ]

        # Set up progress bar and status
        progress_bar = st.empty()
        status = st.empty()

        total = sum(len(clist) for _, clist in all_constraints)
        done = 0

        for constraint_type, constraint_list in all_constraints:
            status.text(f"Processing constraint type: {constraint_type}")

            for constraint in constraint_list:
                done += 1
                progress_bar.progress(done / total)

                if constraint_type in ["BF_SS", "BF_SM", "BF_MS"]:
                    if constraint[3] == "block_force":
                        constraint_copy = constraint.copy()
                        constraint_copy[3] = "block"
                        result_1 = self.process_constraint(constraint_type, constraint_copy)
                        result_1["definition"] = constraint_copy.copy()
                        all_results.append(result_1)

                        constraint_copy[3] = "force"
                        result_2 = self.process_constraint(constraint_type, constraint_copy)
                        result_2["definition"] = constraint_copy.copy()
                        all_results.append(result_2)
                    else:
                        constraint_copy = constraint.copy()
                        result = self.process_constraint(constraint_type, constraint_copy)
                        all_results.append(result)

                elif constraint_type in ["BF_MM", "BF_SM_Grid"]:
                    if constraint[4] == "block_force":
                        constraint_copy = constraint.copy()
                        constraint_copy[4] = "block"
                        result_1 = self.process_constraint(constraint_type, constraint_copy)
                        result_1["definition"] = constraint_copy.copy()
                        all_results.append(result_1)

                        constraint_copy[4] = "force"
                        result_2 = self.process_constraint(constraint_type, constraint_copy)
                        result_2["definition"] = constraint_copy.copy()
                        all_results.append(result_2)
                    else:
                        constraint_copy = constraint.copy()
                        result = self.process_constraint(constraint_type, constraint_copy)
                        all_results.append(result)

                else:
                    result = self.process_constraint(constraint_type, constraint)
                    result["definition"] = constraint.copy()
                    all_results.append(result)

        status.success("All constraints processed ✅")
        return all_results


