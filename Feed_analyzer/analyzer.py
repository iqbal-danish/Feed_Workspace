import os
import sqlite3
import re
import json
import logging
from typing import Dict, Any, List, Tuple, Optional
import config

logger = logging.getLogger(__name__)

def regexp(expr: str, item: Optional[str]) -> bool:
    """Custom SQLite REGEXP function using Python's re module."""
    if item is None:
        return False
    try:
        return re.search(expr, str(item), re.IGNORECASE) is not None
    except Exception:
        return False

def get_db_connection(db_path: str) -> sqlite3.Connection:
    """Returns a SQLite connection with custom functions and dict row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.create_function("REGEXP", 2, regexp)
    # Enable Write-Ahead Log (WAL) mode for better concurrency and write speed
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

class FeedAnalyzerDb:
    """Handles SQLite database schema, dynamic columns, and batch inserts."""
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self.field_mappings: Dict[str, str] = {}  # Maps path -> column_name (e.g. "Location/City" -> "col_1")
        self.next_col_index = 0
        self._init_db()

    def _init_db(self) -> None:
        """Initializes system tables in the SQLite database."""
        conn = sqlite3.connect(self.db_path)
        try:
            # Create system metadata table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feed_info (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            
            # Create schema mapping table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS field_mappings (
                    field_path TEXT PRIMARY KEY,
                    column_name TEXT,
                    field_type TEXT
                )
            """)
            
            # Create records table (starts with primary key and raw content)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    raw_content TEXT
                )
            """)
            conn.commit()
        finally:
            conn.close()
            
        # Load existing field mappings if they exist
        self._load_mappings()

    def open(self) -> None:
        """Opens database connection for transactions."""
        if not self.conn:
            self.conn = get_db_connection(self.db_path)

    def close(self) -> None:
        """Closes database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def __del__(self) -> None:
        """Destructor to ensure connection closure on garbage collection."""
        try:
            self.close()
        except Exception:
            pass

    def _load_mappings(self) -> None:
        """Loads column mappings from the database."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute("SELECT field_path, column_name FROM field_mappings")
            for row in cursor.fetchall():
                path, col = row[0], row[1]
                self.field_mappings[path] = col
                # Keep track of col index to avoid collisions
                match = re.match(r"col_(\d+)", col)
                if match:
                    idx = int(match.group(1))
                    if idx >= self.next_col_index:
                        self.next_col_index = idx + 1
        finally:
            conn.close()

    def _add_new_column(self, field_path: str) -> str:
        """Dynamically adds a column to the records table and maps it."""
        col_name = f"col_{self.next_col_index}"
        self.next_col_index += 1
        
        # Insert mapping first
        assert self.conn is not None
        self.conn.execute(
            "INSERT INTO field_mappings (field_path, column_name, field_type) VALUES (?, ?, ?)",
            (field_path, col_name, "TEXT")
        )
        
        # Alter table to add column (Requires transaction to be temporarily committed/paused in SQLite)
        # SQLite doesn't allow ALTER TABLE inside a transaction on some versions, or it lock-fails.
        # So we temporarily commit the open transaction, run ALTER, and start a new transaction.
        self.conn.commit()
        self.conn.execute(f"ALTER TABLE records ADD COLUMN {col_name} TEXT")
        self.conn.execute("BEGIN")
        
        self.field_mappings[field_path] = col_name
        logger.info(f"Added column {col_name} for field path '{field_path}'")
        return col_name

    def insert_records(self, records_batch: List[Tuple[Dict[str, Any], str]]) -> None:
        """Inserts a batch of records, dynamically adding columns as needed."""
        self.open()
        assert self.conn is not None
        
        # Start transaction block
        self.conn.execute("BEGIN")
        try:
            for record_dict, raw_content in records_batch:
                # 1. Flatten the record dictionary
                flat_data = self._flatten_record(record_dict)
                
                # 2. Check for any new fields not in mappings
                for field_path in flat_data.keys():
                    if field_path not in self.field_mappings:
                        self._add_new_column(field_path)
                
                # 3. Build insert statement dynamically
                columns = ["raw_content"]
                placeholders = ["?"]
                values: List[Any] = [raw_content]
                
                for field_path, val in flat_data.items():
                    col_name = self.field_mappings[field_path]
                    columns.append(col_name)
                    placeholders.append("?")
                    
                    # Convert lists/dicts to JSON strings for robust storage
                    if isinstance(val, (list, dict)):
                        values.append(json.dumps(val, ensure_ascii=False))
                    else:
                        values.append(str(val) if val is not None else None)
                        
                query = f"INSERT INTO records ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
                self.conn.execute(query, values)
                
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed inserting record batch: {e}")
            raise e

    def save_metadata(self, metadata: Dict[str, str]) -> None:
        """Saves metadata key-values to feed_info table."""
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                for k, v in metadata.items():
                    conn.execute(
                        "INSERT OR REPLACE INTO feed_info (key, value) VALUES (?, ?)",
                        (k, str(v))
                    )
        finally:
            conn.close()

    def get_metadata(self) -> Dict[str, str]:
        """Retrieves all metadata from the database."""
        conn = sqlite3.connect(self.db_path)
        metadata = {}
        try:
            cursor = conn.execute("SELECT key, value FROM feed_info")
            for row in cursor.fetchall():
                metadata[row[0]] = row[1]
        finally:
            conn.close()
        return metadata

    def get_schema_tree(self) -> Dict[str, Any]:
        """Constructs a visual schema tree of all paths."""
        paths = list(self.field_mappings.keys())
        tree: Dict[str, Any] = {}
        
        # Sort paths to keep explorer structured
        paths.sort()
        
        for path in paths:
            parts = path.split('/')
            current = tree
            for part in parts:
                if part not in current:
                    current[part] = {}
                current = current[part]
        return tree

    def _flatten_record(self, record: Dict[str, Any], parent_key: str = "", sep: str = "/") -> Dict[str, Any]:
        """Flattens nested dictionaries/lists into dot/slash-separated path keys."""
        items: List[Tuple[str, Any]] = []
        
        if isinstance(record, dict):
            for k, v in record.items():
                new_key = f"{parent_key}{sep}{k}" if parent_key else k
                items.extend(self._flatten_record(v, new_key, sep=sep).items())
        elif isinstance(record, list):
            # Check if it contains nested structures
            has_dict = any(isinstance(x, dict) for x in record)
            if has_dict:
                # Merge keys of nested dictionaries
                merged: Dict[str, List[Any]] = {}
                for obj in record:
                    flat_obj = self._flatten_record(obj, parent_key, sep=sep)
                    for k, v in flat_obj.items():
                        if k not in merged:
                            merged[k] = []
                        merged[k].append(v)
                for k, v in merged.items():
                    items.append((k, v))
            else:
                # Array of primitive values
                items.append((parent_key, record))
        else:
            items.append((parent_key, record))
            
        return dict(items)
