import sqlite3
import logging
from typing import Dict, Any, List, Tuple, Optional
from analyzer import get_db_connection

logger = logging.getLogger(__name__)

def get_field_stats(
    db_path: str,
    field_path: str,
    field_mappings: Dict[str, str]
) -> Dict[str, Any]:
    """Calculates comprehensive statistics for a single field path."""
    col_name = field_mappings.get(field_path)
    if not col_name:
        return {}

    conn = get_db_connection(db_path)
    stats: Dict[str, Any] = {
        "field_path": field_path,
        "present_count": 0,
        "missing_count": 0,
        "unique_count": 0,
        "duplicate_count": 0,
        "min_length": 0,
        "max_length": 0,
        "avg_length": 0.0,
        "completion_rate": 0.0,
        "top_values": [],
        "bottom_values": []
    }

    try:
        # 1. Counts and Lengths in a single query
        query = f"""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN {col_name} IS NOT NULL AND {col_name} != '' THEN 1 ELSE 0 END) as present,
                COUNT(DISTINCT CASE WHEN {col_name} IS NOT NULL AND {col_name} != '' THEN {col_name} ELSE NULL END) as unique_vals,
                MIN(LENGTH({col_name})) as min_len,
                MAX(LENGTH({col_name})) as max_len,
                AVG(LENGTH({col_name})) as avg_len
            FROM records
        """
        row = conn.execute(query).fetchone()
        if row and row["total"] > 0:
            total = row["total"]
            present = row["present"] or 0
            unique_vals = row["unique_vals"] or 0
            
            stats["present_count"] = present
            stats["missing_count"] = total - present
            stats["unique_count"] = unique_vals
            stats["duplicate_count"] = max(present - unique_vals, 0)
            stats["min_length"] = row["min_len"] or 0
            stats["max_length"] = row["max_len"] or 0
            stats["avg_length"] = round(row["avg_len"] or 0.0, 2)
            stats["completion_rate"] = round((present / total) * 100.0, 2) if total > 0 else 0.0

        # 2. Top 10 most common values
        top_query = f"""
            SELECT {col_name} as val, COUNT(*) as cnt
            FROM records
            WHERE {col_name} IS NOT NULL AND {col_name} != ''
            GROUP BY {col_name}
            ORDER BY cnt DESC, val ASC
            LIMIT 10
        """
        top_rows = conn.execute(top_query).fetchall()
        stats["top_values"] = [{"value": r["val"], "count": r["cnt"]} for r in top_rows]

        # 3. Top 10 least common values (bottom values)
        bottom_query = f"""
            SELECT {col_name} as val, COUNT(*) as cnt
            FROM records
            WHERE {col_name} IS NOT NULL AND {col_name} != ''
            GROUP BY {col_name}
            ORDER BY cnt ASC, val ASC
            LIMIT 10
        """
        bottom_rows = conn.execute(bottom_query).fetchall()
        stats["bottom_values"] = [{"value": r["val"], "count": r["cnt"]} for r in bottom_rows]

    except Exception as e:
        logger.error(f"Error calculating stats for field '{field_path}': {e}")
    finally:
        conn.close()

    return stats

def get_multi_group_by(
    db_path: str,
    field_paths: List[str],
    field_mappings: Dict[str, str],
    where_sql: str = "",
    params: List[Any] = None
) -> List[Dict[str, Any]]:
    """Calculates nested/hierarchical group-by counts for given field paths.
    
    Returns:
        A list of dictionaries containing:
        - "keys": List of values in the order of field_paths
        - "count": Count of occurrences
    """
    if not field_paths:
        return []
    
    if params is None:
        params = []

    # Map paths to column names
    col_names = []
    valid_paths = []
    for path in field_paths:
        col = field_mappings.get(path)
        if col:
            col_names.append(col)
            valid_paths.append(path)

    if not col_names:
        return []

    conn = get_db_connection(db_path)
    results = []
    
    try:
        # Build SQL SELECT
        select_cols = ", ".join(col_names)
        where_clause = f"WHERE {where_sql}" if where_sql else ""
        
        query = f"""
            SELECT {select_cols}, COUNT(*) as cnt
            FROM records
            {where_clause}
            GROUP BY {select_cols}
            ORDER BY cnt DESC
        """
        
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        
        for row in rows:
            keys = [row[col] if row[col] is not None else "[Missing]" for col in col_names]
            results.append({
                "keys": keys,
                "count": row["cnt"]
            })
            
    except Exception as e:
        logger.error(f"Error executing group-by on {field_paths}: {e}")
    finally:
        conn.close()
        
    return results

def get_global_statistics(db_path: str, field_mappings: Dict[str, str]) -> Dict[str, Any]:
    """Retrieves high-level summary metrics for the feed."""
    conn = get_db_connection(db_path)
    summary = {
        "total_jobs": 0,
        "total_fields": len(field_mappings),
        "duplicate_id_count": 0,
        "duplicate_id_field": "None"
    }
    
    try:
        row = conn.execute("SELECT COUNT(*) as cnt FROM records").fetchone()
        summary["total_jobs"] = row["cnt"] if row else 0
        
        # Try to find an ID field (e.g. "JobID", "id", "job_id") to count duplicates
        id_field = None
        for path in field_mappings.keys():
            path_lower = path.lower()
            if path_lower in ("jobid", "id", "job_id", "guid", "url", "applyurl"):
                id_field = path
                break
                
        if id_field:
            col_name = field_mappings[id_field]
            dup_query = f"""
                SELECT SUM(dup_cnt) as total_dups FROM (
                    SELECT COUNT(*) - 1 as dup_cnt
                    FROM records
                    WHERE {col_name} IS NOT NULL AND {col_name} != ''
                    GROUP BY {col_name}
                    HAVING COUNT(*) > 1
                )
            """
            dup_row = conn.execute(dup_query).fetchone()
            summary["duplicate_id_count"] = dup_row["total_dups"] if dup_row and dup_row["total_dups"] else 0
            summary["duplicate_id_field"] = id_field

    except Exception as e:
        logger.error(f"Error loading global stats: {e}")
    finally:
        conn.close()
        
    return summary
