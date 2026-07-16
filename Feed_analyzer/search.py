from typing import Dict, Any, List, Tuple, Optional
import logging
from filters import compile_single_filter

logger = logging.getLogger(__name__)

def compile_search(
    query_text: str,
    match_type: str,
    search_field: Optional[str],
    field_mappings: Dict[str, str]
) -> Tuple[str, List[Any]]:
    """Compiles a search request into a SQL WHERE clause and parameters.
    
    Args:
        query_text: The string term to search for.
        match_type: Type of match: "Contains", "Exact Match", "Starts With", "Ends With", "Regex".
        search_field: The field path to search (e.g., "JobID") or None for "All Fields".
        field_mappings: Mappings of paths -> column names.
        
    Returns:
        where_sql: A SQL WHERE string clause.
        params: List of SQL parameters.
    """
    if not query_text:
        return "", []

    # Map match_type to our filter operators
    op_map = {
        "exactmatch": "Equals",
        "contains": "Contains",
        "startswith": "Starts With",
        "endswith": "Ends With",
        "regex": "Regex"
    }
    
    op_clean = match_type.lower().replace(" ", "")
    op = op_map.get(op_clean, "Contains")

    # 1. Search in a specific field
    if search_field and search_field != "all":
        col_name = field_mappings.get(search_field)
        if not col_name:
            logger.warning(f"Search field '{search_field}' not found in mappings.")
            return "0", [] # Safe empty result
        return compile_single_filter(col_name, op, query_text)

    # 2. Search across ALL fields
    clauses = []
    params = []
    
    for field_path, col_name in field_mappings.items():
        clause, bind_vals = compile_single_filter(col_name, op, query_text)
        if clause:
            # We skip 'Missing' and 'Exists' logic for all-field text search
            clauses.append(f"({clause})")
            params.extend(bind_vals)
            
    if not clauses:
        return "", []
        
    # Join with OR to find matches in any of the fields
    return " OR ".join(clauses), params
