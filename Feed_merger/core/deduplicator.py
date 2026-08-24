"""High-performance SQLite and in-memory duplicate detection for streamed XML jobs."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from lxml import etree


class SQLiteDeduplicator:
    """Hybrid in-memory and SQLite duplicate detector for blazing fast O(1) checks."""

    def __init__(self, database_path: Path, duplicate_fields: tuple[str, ...]) -> None:
        self.database_path = database_path
        self.duplicate_fields = duplicate_fields
        self.connection: sqlite3.Connection | None = None
        self._memory_set: set[int] = set()
        self._pending_inserts: list[tuple[str, str]] = []
        self._batch_size = 5000

    def __enter__(self) -> "SQLiteDeduplicator":
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=OFF")
        self.connection.execute("PRAGMA cache_size=-64000")  # 64MB cache
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS job_identifiers (
                field_name TEXT NOT NULL,
                field_value TEXT NOT NULL,
                PRIMARY KEY (field_name, field_value)
            )
            """
        )
        # Pre-load existing hashes into memory set if restarting on existing DB
        cursor = self.connection.execute("SELECT field_name, field_value FROM job_identifiers")
        for row in cursor:
            self._memory_set.add(hash((row[0], row[1])))
        return self

    def __exit__(self, *_: object) -> None:
        self.flush()
        if self.connection is not None:
            self.connection.commit()
            self.connection.close()
            self.connection = None
        self._memory_set.clear()

    def flush(self) -> None:
        """Flush pending batch inserts to SQLite."""
        if self.connection is not None and self._pending_inserts:
            self.connection.executemany(
                "INSERT OR IGNORE INTO job_identifiers (field_name, field_value) VALUES (?, ?)",
                self._pending_inserts,
            )
            self.connection.commit()
            self._pending_inserts.clear()

    def seen(self, element: etree._Element) -> bool:
        """Return True when a job identifier already exists."""
        identifiers: list[tuple[str, str]] = []
        for field in self.duplicate_fields:
            value = self._find_text(element, field)
            if value:
                identifiers.append((field, value.strip().lower()))

        if not identifiers:
            xml_hash = self._canonical_xml_hash(element)
            identifiers.append(("xml_hash", xml_hash))

        # Check in-memory hash set (instant O(1))
        is_duplicate = False
        for f, v in identifiers:
            h = hash((f, v))
            if h in self._memory_set:
                is_duplicate = True
                break

        if is_duplicate:
            return True

        # Not duplicate: register all identifiers in memory set and stage for DB insert
        for f, v in identifiers:
            h = hash((f, v))
            self._memory_set.add(h)
            self._pending_inserts.append((f, v))

        if len(self._pending_inserts) >= self._batch_size:
            self.flush()

        return False

    def _find_text(self, element: etree._Element, field_name: str) -> str | None:
        normalized = field_name.replace("_", "").replace("-", "").lower()
        # Look at direct children first
        for candidate in element.iterchildren():
            local_name = etree.QName(candidate).localname
            candidate_name = local_name.replace("_", "").replace("-", "").lower()
            if candidate_name == normalized:
                text = "".join(candidate.itertext()).strip()
                return text or None
        return None

    def _canonical_xml_hash(self, element: etree._Element) -> str:
        payload = etree.tostring(element, method="c14n").decode("utf-8", errors="ignore")
        return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()
