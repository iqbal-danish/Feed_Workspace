import sqlite3
import logging
from typing import Dict, Any, List
from analyzer import get_db_connection

logger = logging.getLogger(__name__)

def find_duplicates(
    db_path: str,
    field_path: str,
    field_mappings: Dict[str, str],
    limit: int = 1000
) -> List[Dict[str, Any]]:
    """Finds repeating values and counts for a specific field path."""
    col_name = field_mappings.get(field_path)
    if not col_name:
        return []

    conn = get_db_connection(db_path)
    duplicates = []
    
    try:
        query = f"""
            SELECT {col_name} as val, COUNT(*) as cnt
            FROM records
            WHERE {col_name} IS NOT NULL AND {col_name} != ''
            GROUP BY {col_name}
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC
            LIMIT ?
        """
        rows = conn.execute(query, (limit,)).fetchall()
        duplicates = [{"value": r["val"], "count": r["cnt"]} for r in rows]
    except Exception as e:
        logger.error(f"Error finding duplicates for field '{field_path}': {e}")
    finally:
        conn.close()
        
    return duplicates
