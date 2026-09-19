import os
import sqlite3
import re
import json
import logging
from typing import Dict, Any, List, Tuple, Optional
import config
import duckdb

class DictRow:
    """A wrapper for database result rows that allows access by both column index and column name."""
    def __init__(self, values: tuple, description: list):
        self._values = values
        self._mapping = {desc[0].lower(): i for i, desc in enumerate(description)} if description else {}

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            idx = self._mapping.get(key.lower())
            if idx is not None:
                return self._values[idx]
            raise KeyError(f"Column '{key}' not found in row mappings.")
        return self._values[key]

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return repr(self._values)

    def keys(self) -> List[str]:
        return list(self._mapping.keys())

class DuckDBConnectionWrapper:
    """Wrapper around duckdb connection to emulate SQLite dict row factory."""
    def __init__(self, conn: duckdb.DuckDBPyConnection):
        self._conn = conn

    def execute(self, query: str, params: Optional[list] = None) -> 'DuckDBCursorWrapper':
        if params is not None:
            res = self._conn.execute(query, params)
        else:
            res = self._conn.execute(query)
        return DuckDBCursorWrapper(res)

    def close(self) -> None:
        self._conn.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

class DuckDBCursorWrapper:
    def __init__(self, relation: Any):
        self._relation = relation
        self._description = relation.description

    def fetchone(self) -> Optional[DictRow]:
        row = self._relation.fetchone()
        if row is None:
            return None
        return DictRow(row, self._description)

    def fetchall(self) -> List[DictRow]:
        rows = self._relation.fetchall()
        return [DictRow(r, self._description) for r in rows]

    @property
    def description(self) -> list:
        return self._description

    def __getattr__(self, name: str) -> Any:
        return getattr(self._relation, name)

def get_analytics_connection(db_path: str):
    """Returns a wrapped DuckDB in-memory connection attached to the SQLite database for ultra-fast vectorized OLAP querying."""
    conn = duckdb.connect(":memory:")
    conn.execute("INSTALL sqlite; LOAD sqlite;")
    abs_p = os.path.abspath(db_path).replace("\\", "/")
    conn.execute(f"ATTACH '{abs_p}' AS sqlite_db (TYPE SQLITE)")
    conn.execute("SET search_path = 'sqlite_db'")
    return DuckDBConnectionWrapper(conn)

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
    """Returns a SQLite connection with high-speed memory-mapped I/O pragmas and dict row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.create_function("REGEXP", 2, regexp)
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA page_size = 65536")
    conn.execute("PRAGMA cache_size = -128000")
    conn.execute("PRAGMA mmap_size = 30000000000")
    return conn

class FeedAnalyzerDb:
    """Handles high-throughput SQLite schema initialization, dynamic columns, and streaming commits."""
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self.field_mappings: Dict[str, str] = {}  # Maps path -> column_name (e.g. "Location/City" -> "col_1")
        self.known_fields_set: set = set()
        self.next_col_index = 0
        self._init_db()

    def _init_db(self) -> None:
        """Initializes system tables in the high-speed SQLite database."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA synchronous = OFF")
            conn.execute("PRAGMA journal_mode = MEMORY")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feed_info (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS field_mappings (
                    field_path TEXT PRIMARY KEY,
                    column_name TEXT,
                    field_type TEXT
                )
            """)
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
        """Opens database connections for transactions."""
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
                self.known_fields_set.add(path)
                # Keep track of col index to avoid collisions
                match = re.match(r"col_(\d+)", col)
                if match:
                    idx = int(match.group(1))
                    if idx >= self.next_col_index:
                        self.next_col_index = idx + 1
        finally:
            conn.close()

    def _add_new_column(self, field_path: str) -> str:
        """Dynamically adds a column to SQLite structure in autocommit mode."""
        col_name = f"col_{self.next_col_index}"
        self.next_col_index += 1
        
        assert self.conn is not None
        self.conn.execute(
            "INSERT INTO field_mappings (field_path, column_name, field_type) VALUES (?, ?, ?)",
            (field_path, col_name, "TEXT")
        )
        self.conn.execute(f"ALTER TABLE records ADD COLUMN {col_name} TEXT")
        self.conn.commit()
        
        self.field_mappings[field_path] = col_name
        self.known_fields_set.add(field_path)
        logger.info(f"Added column {col_name} for field path '{field_path}'")
        return col_name

    def insert_records(self, records_batch: List[Tuple[Dict[str, Any], str]]) -> None:
        """Inserts a batch of records into SQLite using single-pass sparse mapping and high-throughput executemany."""
        if not records_batch:
            return

        self.open()
        assert self.conn is not None
        
        # 1. Identify any new columns in this batch and flatten records once
        flattened_batch: List[Tuple[Dict[str, Any], str]] = []
        new_fields: List[str] = []
        
        for record_dict, raw_content in records_batch:
            # Bypass recursive flattening if records are already flat (e.g. from Rust native streamer)
            if any(isinstance(v, dict) for v in record_dict.values()):
                flat_data = self._flatten_record(record_dict)
            else:
                flat_data = record_dict
            flattened_batch.append((flat_data, raw_content))
            
            for field_path in flat_data.keys():
                if field_path not in self.known_fields_set:
                    if field_path not in new_fields:
                        new_fields.append(field_path)
                    
        for field_path in new_fields:
            self._add_new_column(field_path)
            
        # 2. Build the fixed columns query for executemany
        sorted_fields = sorted(self.field_mappings.keys())
        columns = ["raw_content"] + [self.field_mappings[f] for f in sorted_fields]
        placeholders = ["?"] * len(columns)
        query = f"INSERT INTO records ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
        
        # Build column index mapping for O(K) sparse row construction
        field_to_idx = {field: i + 1 for i, field in enumerate(sorted_fields)}
        num_columns = len(columns)
        
        # 3. Prepare parameters for all rows using the single flattened batch
        row_values = []
        for flat_data, raw_content in flattened_batch:
            vals = [None] * num_columns
            vals[0] = raw_content
            
            for field_path, val in flat_data.items():
                idx = field_to_idx.get(field_path)
                if idx is not None:
                    if isinstance(val, (list, dict)):
                        vals[idx] = json.dumps(val, ensure_ascii=False)
                    else:
                        vals[idx] = str(val) if val is not None else None
            row_values.append(vals)
            
        # 4. Perform high-speed bulk insertion under a single transaction
        self.conn.execute("BEGIN TRANSACTION")
        try:
            self.conn.executemany(query, row_values)
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed inserting record batch: {e}")
            raise e

    def create_indexes(self) -> None:
        """Finalizes SQLite storage checkpoint."""
        self.open()
        assert self.conn is not None
        self.conn.commit()

    def save_metadata(self, metadata: Dict[str, str]) -> None:
        """Saves metadata key-values to feed_info table."""
        if self.conn:
            with self.conn:
                for k, v in metadata.items():
                    self.conn.execute(
                        "INSERT OR REPLACE INTO feed_info (key, value) VALUES (?, ?)",
                        (k, str(v))
                    )
        else:
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
        metadata = {}
        if self.conn:
            cursor = self.conn.execute("SELECT key, value FROM feed_info")
            for row in cursor.fetchall():
                metadata[row[0]] = row[1]
        else:
            conn = sqlite3.connect(self.db_path)
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
