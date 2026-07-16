import sqlite3
from typing import Dict, Any, List
from analyzer import get_db_connection
from statistics import get_field_stats

def generate_missing_value_report(
    db_path: str,
    field_mappings: Dict[str, str]
) -> List[Dict[str, Any]]:
    """Generates a completeness report for all fields, sorted by lowest completion."""
    report = []
    for field_path in field_mappings.keys():
        stats = get_field_stats(db_path, field_path, field_mappings)
        if stats:
            report.append({
                "field_path": field_path,
                "completion_rate": stats["completion_rate"],
                "present_count": stats["present_count"],
                "missing_count": stats["missing_count"]
            })
            
    # Sort by lowest completion rate first
    report.sort(key=lambda x: x["completion_rate"])
    return report

def generate_duplicate_summary(
    db_path: str,
    field_mappings: Dict[str, str]
) -> List[Dict[str, Any]]:
    """Discovers which fields contain duplicate values and returns a summary list."""
    conn = get_db_connection(db_path)
    summary = []
    
    try:
        for field_path, col_name in field_mappings.items():
            # Quick query to check if there are any duplicate values
            query = f"""
                SELECT COUNT(*) as dup_groups
                FROM (
                    SELECT 1
                    FROM records
                    WHERE {col_name} IS NOT NULL AND {col_name} != ''
                    GROUP BY {col_name}
                    HAVING COUNT(*) > 1
                )
            """
            row = conn.execute(query).fetchone()
            dup_groups = row["dup_groups"] if row else 0
            if dup_groups > 0:
                # Count total duplicate items
                total_dup_query = f"""
                    SELECT SUM(cnt) as total_dups FROM (
                        SELECT COUNT(*) as cnt
                        FROM records
                        WHERE {col_name} IS NOT NULL AND {col_name} != ''
                        GROUP BY {col_name}
                        HAVING COUNT(*) > 1
                    )
                """
                total_row = conn.execute(total_dup_query).fetchone()
                total_dups = total_row["total_dups"] if total_row and total_row["total_dups"] else 0
                
                summary.append({
                    "field_path": field_path,
                    "duplicate_groups": dup_groups,
                    "total_duplicates": total_dups
                })
    except Exception:
        pass
    finally:
        conn.close()
        
    summary.sort(key=lambda x: x["total_duplicates"], reverse=True)
    return summary
