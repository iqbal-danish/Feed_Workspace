"""SQLite-backed duplicate detection for streamed XML jobs."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from lxml import etree


class SQLiteDeduplicator:
    """Store only compact SHA256 fingerprints for duplicate detection."""

    def __init__(self, database_path: Path, duplicate_fields: tuple[str, ...]) -> None:
        self.database_path = database_path
        self.duplicate_fields = duplicate_fields
        self.connection: sqlite3.Connection | None = None

    def __enter__(self) -> "SQLiteDeduplicator":
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS job_identifiers (
                field_name TEXT NOT NULL,
                field_value TEXT NOT NULL,
                PRIMARY KEY (field_name, field_value)
            )
            """
        )
        return self

    def __exit__(self, *_: object) -> None:
        if self.connection is not None:
            self.connection.commit()
            self.connection.close()

    def seen(self, element: etree._Element) -> bool:
        """Return True when a job identifier already exists in the database."""
        assert self.connection is not None
        identifiers: list[tuple[str, str]] = []
        for field in self.duplicate_fields:
            value = self._find_text(element, field)
            if value:
                identifiers.append((field, value.strip().lower()))

        if not identifiers:
            xml_hash = self._canonical_xml_hash(element)
            identifiers.append(("xml_hash", xml_hash))

        # Check if any of these identifiers have been seen before
        placeholders = " OR ".join("(field_name = ? AND field_value = ?)" for _ in identifiers)
        query = f"SELECT 1 FROM job_identifiers WHERE {placeholders}"
        params: list[str] = []
        for f, v in identifiers:
            params.extend([f, v])

        cursor = self.connection.execute(query, params)
        if cursor.fetchone():
            return True

        # If not seen, record all identifiers for this job
        for f, v in identifiers:
            self.connection.execute(
                "INSERT OR IGNORE INTO job_identifiers (field_name, field_value) VALUES (?, ?)",
                (f, v),
            )
        return False

    def _find_text(self, element: etree._Element, field_name: str) -> str | None:
        normalized = field_name.replace("_", "").replace("-", "").lower()
        # Only look at direct children of the job element to avoid matching nested structures (like company ID)
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
