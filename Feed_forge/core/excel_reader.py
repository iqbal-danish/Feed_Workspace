import os
import pandas as pd
import numpy as np

class ExcelReader:
    """Helper class to load Excel workbooks and extract sheet names and previews."""
    
    @staticmethod
    def get_sheet_names(filepath: str) -> list[str]:
        """Read the sheet names from an Excel file."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")
        
        try:
            # Load with pandas ExcelFile (faster for just reading metadata)
            xls = pd.ExcelFile(filepath, engine='openpyxl')
            return xls.sheet_names
        except Exception as e:
            raise ValueError(f"Failed to read sheets from Excel file: {str(e)}")
            
    @staticmethod
    def get_sheet_preview(filepath: str, sheet_name: str, max_rows: int = 100) -> dict:
        """
        Read the first `max_rows` rows of a sheet and return columns and rows
        in a format compatible with AG Grid.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")
            
        try:
            # Read sheet using pandas
            df = pd.read_excel(filepath, sheet_name=sheet_name, nrows=max_rows, engine='openpyxl')
            
            # Replace NaNs/Infs with None for JSON serialization
            df = df.replace([np.inf, -np.inf], None)
            df = df.replace({np.nan: None})
            
            # Format datetime columns as strings
            for col in df.columns:
                if pd.api.types.is_datetime64_any_dtype(df[col]):
                    # Format as YYYY-MM-DD or standard datetime string, handling NaT/None
                    df[col] = df[col].apply(
                        lambda val: val.strftime('%Y-%m-%d %H:%M:%S') if pd.notnull(val) else None
                    )
            
            # Generate AG Grid compatible column definitions
            # We map column names to string field keys to avoid issues with special characters/spaces
            columns = []
            for i, col in enumerate(df.columns):
                col_name = str(col)
                # Field ID will be clean alphanumeric like 'col_0', 'col_1' to avoid duplicate columns
                field_id = f"col_{i}"
                columns.append({
                    "headerName": col_name,
                    "field": field_id
                })
            
            # Convert rows to map to field_ids instead of raw column headers
            data_records = []
            for _, row in df.iterrows():
                record = {}
                for i, col in enumerate(df.columns):
                    field_id = f"col_{i}"
                    record[field_id] = row[col]
                data_records.append(record)
                
            return {
                "columns": columns,
                "data": data_records,
                "total_rows": len(df)
            }
        except Exception as e:
            raise ValueError(f"Failed to read worksheet '{sheet_name}': {str(e)}")
