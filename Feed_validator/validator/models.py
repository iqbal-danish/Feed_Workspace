"""
Data models for XML Validator Pro.

Defines all core data structures used throughout the application
including validation errors, file info, progress tracking, and settings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class ErrorSeverity(Enum):
    """Severity levels for validation errors."""
    WARNING = "Warning"
    ERROR = "Error"
    FATAL = "Fatal"


class ErrorCategory(Enum):
    """Categories of XML validation errors."""
    TAG_MISMATCH = "Tag Mismatch"
    INVALID_ENCODING = "Invalid Encoding"
    MALFORMED_XML = "Malformed XML"
    INVALID_ENTITY = "Invalid Entity"
    MALFORMED_CDATA = "Malformed CDATA"
    UNEXPECTED_EOF = "Unexpected EOF"
    DUPLICATE_DECLARATION = "Duplicate Declaration"
    NAMESPACE_ERROR = "Namespace Error"
    ILLEGAL_CHARACTER = "Illegal Character"
    INVALID_ATTRIBUTE = "Invalid Attribute"
    INVALID_UTF8 = "Invalid UTF-8"
    OTHER = "Other"


@dataclass
class ContextLine:
    """A single line of context around an error."""
    line_number: int
    text: str
    is_error_line: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "line_number": self.line_number,
            "text": self.text,
            "is_error_line": self.is_error_line,
        }


@dataclass
class ValidationError:
    """Represents a single XML validation error."""
    error_number: int
    line: int
    column: int
    byte_offset: int
    message: str
    category: ErrorCategory
    severity: ErrorSeverity
    context_lines: list[ContextLine] = field(default_factory=list)
    # Structured tag info extracted from the lxml message
    tag_name: str = ""        # The problematic tag/field name (e.g. "job")
    reference_tag: str = ""   # The mismatched partner tag name (e.g. "jobs")
    reference_line: int = 0   # Line where the partner/opening tag was seen

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "error_number": self.error_number,
            "line": self.line,
            "column": self.column,
            "byte_offset": self.byte_offset,
            "message": self.message,
            "category": self.category.value,
            "severity": self.severity.value,
            "context_lines": [cl.to_dict() for cl in self.context_lines],
            "tag_name": self.tag_name,
            "reference_tag": self.reference_tag,
            "reference_line": self.reference_line,
        }


@dataclass
class FileInfo:
    """Metadata about the XML file being validated."""
    filename: str = ""
    absolute_path: str = ""
    file_size: int = 0
    encoding: str = "utf-8"
    xml_version: str = "1.0"
    line_count: Optional[int] = None
    root_element: str = ""
    namespace_count: int = 0
    last_modified: str = ""
    validation_duration: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return asdict(self)


@dataclass
class ValidationProgress:
    """Real-time progress data during validation."""
    bytes_processed: int = 0
    total_bytes: int = 0
    current_line: int = 0
    percent_complete: float = 0.0
    elapsed_seconds: float = 0.0
    estimated_remaining_seconds: float = 0.0
    processing_speed_mbps: float = 0.0
    errors_found: int = 0

    @property
    def is_complete(self) -> bool:
        """Whether validation has processed all bytes."""
        return self.bytes_processed >= self.total_bytes and self.total_bytes > 0


@dataclass
class ValidationResult:
    """Complete result of a validation run."""
    file_info: FileInfo
    errors: list[ValidationError] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: float = 0.0
    was_cancelled: bool = False
    summary_stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "file_info": self.file_info.to_dict(),
            "errors": [e.to_dict() for e in self.errors],
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "was_cancelled": self.was_cancelled,
            "summary_stats": self.summary_stats,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @property
    def error_count(self) -> int:
        """Total number of errors."""
        return len(self.errors)

    @property
    def has_errors(self) -> bool:
        """Whether any errors were found."""
        return len(self.errors) > 0

    def compute_summary(self) -> None:
        """Compute summary statistics from the error list."""
        severity_counts: dict[str, int] = {}
        category_counts: dict[str, int] = {}
        for error in self.errors:
            sev = error.severity.value
            cat = error.category.value
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
            category_counts[cat] = category_counts.get(cat, 0) + 1
        self.summary_stats = {
            "total_errors": len(self.errors),
            "by_severity": severity_counts,
            "by_category": category_counts,
        }


@dataclass
class AppSettings:
    """Application settings persisted between sessions."""
    context_line_count: int = 10
    theme: str = "dark"
    font_size: int = 12
    auto_open_last_file: bool = False
    report_output_directory: str = ""
    max_recent_files: int = 10
    recent_files: list[str] = field(default_factory=list)
    window_geometry: Optional[bytes] = None
    window_state: Optional[bytes] = None

    def add_recent_file(self, file_path: str) -> None:
        """Add a file to the recent files list, keeping it bounded."""
        if file_path in self.recent_files:
            self.recent_files.remove(file_path)
        self.recent_files.insert(0, file_path)
        if len(self.recent_files) > self.max_recent_files:
            self.recent_files = self.recent_files[: self.max_recent_files]

    def clear_recent_files(self) -> None:
        """Clear the recent files list."""
        self.recent_files.clear()
