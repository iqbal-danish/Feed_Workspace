import os
import csv
import json
import sqlite3
import pandas as pd
from typing import List, Dict, Any, Tuple
from analyzer import get_db_connection

def query_to_dataframe(
    db_path: str,
    query_sql: str,
    params: List[Any],
    field_mappings: Dict[str, str]
) -> pd.DataFrame:
    """Runs a query on SQLite and returns a Pandas DataFrame with original path headers."""
    conn = get_db_connection(db_path)
    try:
        # Load query into DataFrame
        df = pd.read_sql_query(query_sql, conn, params=params)
        
        # Reverse mapping: col_name -> field_path
        reverse_mappings = {v: k for k, v in field_mappings.items()}
        
        # We also have special columns: "id", "raw_content"
        # Let's map them to user friendly names
        rename_dict = {
            "id": "Record ID",
            "raw_content": "Raw XML/JSON Content"
        }
        for col in df.columns:
            if col in reverse_mappings:
                rename_dict[col] = reverse_mappings[col]
                
        df.rename(columns=rename_dict, inplace=True)
        return df
    finally:
        conn.close()

def export_csv(df: pd.DataFrame, output_path: str) -> None:
    """Exports DataFrame to a CSV file."""
    df.to_csv(output_path, index=False, encoding='utf-8-sig')

def export_excel(df: pd.DataFrame, output_path: str) -> None:
    """Exports DataFrame to an Excel file using openpyxl."""
    # Ensure openpyxl writer is used
    df.to_excel(output_path, index=False, engine='openpyxl')

def export_json(df: pd.DataFrame, output_path: str) -> None:
    """Exports DataFrame to a JSON file."""
    df.to_json(output_path, orient='records', force_ascii=False, indent=2)

def export_html_report(
    summary_data: Dict[str, Any],
    stats_data: List[Dict[str, Any]],
    output_path: str
) -> None:
    """Generates a standalone, beautiful HTML analytical report file."""
    # Simple self-contained HTML page template
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Feed Analysis Report - {summary_data.get('filename', 'Feed')}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #0f172a;
            color: #f1f5f9;
            margin: 0;
            padding: 40px;
        }}
        .card {{
            background: rgba(30, 41, 59, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
        }}
        h1, h2 {{
            color: #6366f1;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
        }}
        .metric-label {{
            font-size: 0.875rem;
            color: #94a3b8;
        }}
        .metric-value {{
            font-size: 1.5rem;
            font-weight: 600;
            color: #38bdf8;
            margin-top: 4px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 16px;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }}
        th {{
            background-color: rgba(99, 102, 241, 0.1);
            color: #818cf8;
        }}
        tr:hover {{
            background-color: rgba(255, 255, 255, 0.02);
        }}
    </style>
</head>
<body>
    <div class="card">
        <h1>XML/JSON Feed Analysis Summary</h1>
        <p style="color: #94a3b8;">Generated on {summary_data.get('date', 'Unknown Date')}</p>
        <div class="grid">
            <div>
                <div class="metric-label">Filename</div>
                <div class="metric-value">{summary_data.get('filename')}</div>
            </div>
            <div>
                <div class="metric-label">File Size</div>
                <div class="metric-value">{summary_data.get('file_size')}</div>
            </div>
            <div>
                <div class="metric-label">Total Records</div>
                <div class="metric-value">{summary_data.get('total_jobs')}</div>
            </div>
            <div>
                <div class="metric-label">Processing Time</div>
                <div class="metric-value">{summary_data.get('processing_time')} s</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h2>Field Statistics</h2>
        <table>
            <thead>
                <tr>
                    <th>Field Path</th>
                    <th>Completion %</th>
                    <th>Present Count</th>
                    <th>Missing Count</th>
                    <th>Unique Count</th>
                    <th>Avg Text Length</th>
                </tr>
            </thead>
            <tbody>
    """
    
    for stat in stats_data:
        html_content += f"""
                <tr>
                    <td style="font-weight:600;color:#38bdf8;">{stat.get('field_path')}</td>
                    <td>{stat.get('completion_rate')}%</td>
                    <td>{stat.get('present_count')}</td>
                    <td>{stat.get('missing_count')}</td>
                    <td>{stat.get('unique_count')}</td>
                    <td>{stat.get('avg_length')} char</td>
                </tr>
        """
        
    html_content += """
            </tbody>
        </table>
    </div>
</body>
</html>
    """
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
