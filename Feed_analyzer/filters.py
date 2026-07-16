from typing import List, Dict, Any, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

def compile_filters(
    filters: List[Dict[str, Any]], 
    field_mappings: Dict[str, str]
) -> Tuple[str, List[Any]]:
    """Compiles visual filter parameters into a parameterized SQL WHERE clause.
    
    Each filter dict should contain:
        - "field": the XML/JSON field path (e.g. "Location/City")
        - "operator": the operator name (e.g. "Contains", "Equals")
        - "value": the comparison value string (optional for some operators)
        
    Returns:
        - where_sql: A SQL string, e.g., "(col_0 = ?) AND (col_1 REGEXP ?)"
        - params: List of bind parameters
    """
    if not filters:
        return "", []

    clauses = []
    params = []

    for filt in filters:
        field = filt.get("field")
        op = filt.get("operator")
        val = filt.get("value", "")

        # Skip invalid filters
        if not field or not op:
            continue

        col_name = field_mappings.get(field)
        if not col_name:
            # If the field doesn't exist in mappings, it cannot match any records
            logger.warning(f"Filter field '{field}' not found in database mappings.")
            clauses.append("0")  # Force empty result set safely
            continue

        clause, bind_vals = compile_single_filter(col_name, op, val)
        if clause:
            clauses.append(f"({clause})")
            params.extend(bind_vals)

    if not clauses:
        return "", []

    return " AND ".join(clauses), params

def compile_single_filter(col_name: str, op: str, val: str) -> Tuple[str, List[Any]]:
    """Compiles a single column operator and value into a SQL segment and its parameters."""
    op_lower = op.lower().replace(" ", "")

    if op_lower == "equals":
        return f"{col_name} = ?", [val]
    elif op_lower == "notequals":
        # Handle SQLite's behavior where NULL values don't match standard inequality operators
        return f"({col_name} != ? OR {col_name} IS NULL)", [val]
    elif op_lower == "contains":
        return f"{col_name} LIKE ?", [f"%{val}%"]
    elif op_lower == "startswith":
        return f"{col_name} LIKE ?", [f"{val}%"]
    elif op_lower == "endswith":
        return f"{col_name} LIKE ?", [f"%{val}"]
    elif op_lower == "greaterthan":
        try:
            # Try to cast to float to support numeric comparisons
            num_val = float(val)
            return f"CAST({col_name} AS REAL) > ?", [num_val]
        except ValueError:
            # Fallback to string comparison if not numeric
            return f"{col_name} > ?", [val]
    elif op_lower == "lessthan":
        try:
            num_val = float(val)
            return f"CAST({col_name} AS REAL) < ?", [num_val]
        except ValueError:
            return f"{col_name} < ?", [val]
    elif op_lower == "exists":
        return f"({col_name} IS NOT NULL AND {col_name} != '')", []
    elif op_lower == "missing":
        return f"({col_name} IS NULL OR {col_name} = '')", []
    elif op_lower in ("inlist", "notinlist"):
        # Split by comma and strip values
        items = [i.strip() for i in val.split(",") if i.strip()]
        if not items:
            # Return logic that evaluates to false / true depending on the operator
            if op_lower == "inlist":
                return "0", []
            else:
                return "1", []
        placeholders = ", ".join(["?"] * len(items))
        if op_lower == "inlist":
            return f"{col_name} IN ({placeholders})", items
        else:
            return f"({col_name} NOT IN ({placeholders}) OR {col_name} IS NULL)", items
    elif op_lower == "regex":
        return f"{col_name} REGEXP ?", [val]
    else:
        logger.warning(f"Unknown filter operator: {op}")
        return "", []
