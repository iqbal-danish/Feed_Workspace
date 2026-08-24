import sqlite3
import logging
from typing import Dict, Any, List, Tuple, Optional
from analyzer import get_analytics_connection

logger = logging.getLogger(__name__)

_field_stats_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}

def get_field_stats(
    db_path: str,
    field_path: str,
    field_mappings: Dict[str, str]
) -> Dict[str, Any]:
    """Calculates comprehensive statistics for a single field path with single-pass aggregation and in-memory caching."""
    col_name = field_mappings.get(field_path)
    if not col_name:
        return {}

    cache_key = (db_path, field_path)
    if cache_key in _field_stats_cache:
        return _field_stats_cache[cache_key]

    conn = get_analytics_connection(db_path)
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
        # 1. Total records count
        total_row = conn.execute("SELECT COUNT(*) as total FROM records").fetchone()
        total = total_row["total"] if total_row else 0

        # 2. Single-pass Group By aggregation for present count, unique count, min/max/avg lengths, top 10, and bottom 10
        q = f"""
            SELECT {col_name} as val, COUNT(*) as cnt, LENGTH({col_name}) as len
            FROM records
            WHERE {col_name} IS NOT NULL AND {col_name} != ''
            GROUP BY {col_name}, LENGTH({col_name})
        """
        rows = conn.execute(q).fetchall()
        
        if total > 0:
            present = sum(r["cnt"] for r in rows)
            unique_vals = len(rows)
            min_len = min((r["len"] for r in rows if r["len"] is not None), default=0)
            max_len = max((r["len"] for r in rows if r["len"] is not None), default=0)
            total_chars = sum(r["cnt"] * (r["len"] or 0) for r in rows)
            avg_len = round(total_chars / present, 2) if present > 0 else 0.0
            
            stats["present_count"] = present
            stats["missing_count"] = total - present
            stats["unique_count"] = unique_vals
            stats["duplicate_count"] = max(present - unique_vals, 0)
            stats["min_length"] = min_len
            stats["max_length"] = max_len
            stats["avg_length"] = avg_len
            stats["completion_rate"] = round((present / total) * 100.0, 2)
            
            # Sort for Top 10 DESC and Bottom 10 ASC
            sorted_desc = sorted(rows, key=lambda x: (-x["cnt"], str(x["val"])))
            sorted_asc = sorted(rows, key=lambda x: (x["cnt"], str(x["val"])))
            
            stats["top_values"] = [{"value": r["val"], "count": r["cnt"]} for r in sorted_desc[:10]]
            stats["bottom_values"] = [{"value": r["val"], "count": r["cnt"]} for r in sorted_asc[:10]]

        _field_stats_cache[cache_key] = stats

    except Exception as e:
        logger.error(f"Error calculating stats for field '{field_path}': {e}")
    finally:
        conn.close()

    return stats

def precache_field_stats(db_path: str, field_mappings: Dict[str, str]) -> None:
    """Pre-calculates and caches field statistics in background for top fields."""
    logger.info(f"Starting background field stats pre-caching for {len(field_mappings)} fields...")
    priority_keywords = ['title', 'company', 'location', 'city', 'cpc', 'category', 'country', 'state']
    sorted_fields = sorted(
        field_mappings.keys(),
        key=lambda f: 0 if any(k in f.lower() for k in priority_keywords) else 1
    )
    for field_path in sorted_fields[:15]:
        try:
            get_field_stats(db_path, field_path, field_mappings)
        except Exception as e:
            logger.warning(f"Failed pre-caching field '{field_path}': {e}")
    logger.info("Field stats pre-caching complete.")

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

    conn = get_analytics_connection(db_path)
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
    conn = get_analytics_connection(db_path)
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
