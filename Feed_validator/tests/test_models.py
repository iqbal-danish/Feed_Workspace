"""
Tests for validator.models — all core data structures.

Covers enums, dataclasses, serialization, computed properties, and
mutable-state helpers (recent files, summary computation).
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from validator.models import (
    AppSettings,
    ContextLine,
    ErrorCategory,
    ErrorSeverity,
    FileInfo,
    ValidationError,
    ValidationProgress,
    ValidationResult,
)


# ╔══════════════════════════════════════════════════════════════════╗
# ║  Enum tests                                                     ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestErrorSeverity:
    """ErrorSeverity enum should expose Warning, Error, Fatal."""

    @pytest.mark.parametrize(
        "member, expected_value",
        [
            (ErrorSeverity.WARNING, "Warning"),
            (ErrorSeverity.ERROR, "Error"),
            (ErrorSeverity.FATAL, "Fatal"),
        ],
    )
    def test_severity_values(self, member: ErrorSeverity, expected_value: str):
        assert member.value == expected_value

    def test_severity_member_count(self):
        assert len(ErrorSeverity) == 3


class TestErrorCategory:
    """ErrorCategory enum should list every recognised category."""

    EXPECTED_CATEGORIES = {
        "TAG_MISMATCH": "Tag Mismatch",
        "INVALID_ENCODING": "Invalid Encoding",
        "MALFORMED_XML": "Malformed XML",
        "INVALID_ENTITY": "Invalid Entity",
        "MALFORMED_CDATA": "Malformed CDATA",
        "UNEXPECTED_EOF": "Unexpected EOF",
        "DUPLICATE_DECLARATION": "Duplicate Declaration",
        "NAMESPACE_ERROR": "Namespace Error",
        "ILLEGAL_CHARACTER": "Illegal Character",
        "INVALID_ATTRIBUTE": "Invalid Attribute",
        "INVALID_UTF8": "Invalid UTF-8",
        "OTHER": "Other",
    }

    @pytest.mark.parametrize(
        "name, expected_value",
        list(EXPECTED_CATEGORIES.items()),
    )
    def test_category_values(self, name: str, expected_value: str):
        member = ErrorCategory[name]
        assert member.value == expected_value

    def test_category_member_count(self):
        assert len(ErrorCategory) == 12


# ╔══════════════════════════════════════════════════════════════════╗
# ║  ContextLine                                                     ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestContextLine:
    """ContextLine stores a single line of context with an error flag."""

    def test_creation_defaults(self):
        cl = ContextLine(line_number=5, text="<root>")
        assert cl.line_number == 5
        assert cl.text == "<root>"
        assert cl.is_error_line is False

    def test_creation_error_line(self):
        cl = ContextLine(line_number=10, text="<bad/>", is_error_line=True)
        assert cl.is_error_line is True

    def test_to_dict(self):
        cl = ContextLine(line_number=3, text="  <item/>", is_error_line=True)
        d = cl.to_dict()
        assert d == {
            "line_number": 3,
            "text": "  <item/>",
            "is_error_line": True,
        }


# ╔══════════════════════════════════════════════════════════════════╗
# ║  ValidationError                                                 ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestValidationError:
    """ValidationError captures one XML error with context."""

    @pytest.fixture
    def sample_error(self) -> ValidationError:
        return ValidationError(
            error_number=1,
            line=42,
            column=8,
            byte_offset=1024,
            message="Opening and ending tag mismatch",
            category=ErrorCategory.TAG_MISMATCH,
            severity=ErrorSeverity.ERROR,
            context_lines=[
                ContextLine(41, "  <title>Hello", False),
                ContextLine(42, "  </author>", True),
                ContextLine(43, "  <price/>", False),
            ],
        )

    def test_creation(self, sample_error: ValidationError):
        assert sample_error.error_number == 1
        assert sample_error.line == 42
        assert sample_error.column == 8
        assert sample_error.byte_offset == 1024
        assert sample_error.category is ErrorCategory.TAG_MISMATCH
        assert sample_error.severity is ErrorSeverity.ERROR

    def test_to_dict_structure(self, sample_error: ValidationError):
        d = sample_error.to_dict()
        assert d["error_number"] == 1
        assert d["line"] == 42
        assert d["column"] == 8
        assert d["byte_offset"] == 1024
        assert d["message"] == "Opening and ending tag mismatch"
        # Enums must be serialised as their string values
        assert d["category"] == "Tag Mismatch"
        assert d["severity"] == "Error"

    def test_to_dict_context_lines(self, sample_error: ValidationError):
        d = sample_error.to_dict()
        assert len(d["context_lines"]) == 3
        assert d["context_lines"][1]["is_error_line"] is True

    def test_empty_context_lines(self):
        err = ValidationError(
            error_number=1,
            line=1,
            column=1,
            byte_offset=0,
            message="error",
            category=ErrorCategory.OTHER,
            severity=ErrorSeverity.WARNING,
        )
        assert err.context_lines == []
        assert err.to_dict()["context_lines"] == []


# ╔══════════════════════════════════════════════════════════════════╗
# ║  FileInfo                                                        ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestFileInfo:
    """FileInfo holds metadata about the file being validated."""

    def test_defaults(self):
        fi = FileInfo()
        assert fi.filename == ""
        assert fi.file_size == 0
        assert fi.encoding == "utf-8"
        assert fi.xml_version == "1.0"
        assert fi.line_count is None
        assert fi.namespace_count == 0

    def test_populated(self):
        fi = FileInfo(
            filename="test.xml",
            absolute_path="/tmp/test.xml",
            file_size=2048,
            encoding="utf-16",
            xml_version="1.1",
            line_count=100,
            root_element="catalog",
            namespace_count=3,
            last_modified="2024-01-01T00:00:00",
            validation_duration=1.5,
        )
        assert fi.filename == "test.xml"
        assert fi.file_size == 2048
        assert fi.namespace_count == 3
        assert fi.validation_duration == 1.5

    def test_to_dict_keys(self):
        fi = FileInfo(filename="data.xml", file_size=512)
        d = fi.to_dict()
        expected_keys = {
            "filename",
            "absolute_path",
            "file_size",
            "encoding",
            "xml_version",
            "line_count",
            "root_element",
            "namespace_count",
            "last_modified",
            "validation_duration",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_values(self):
        fi = FileInfo(filename="data.xml", file_size=512)
        d = fi.to_dict()
        assert d["filename"] == "data.xml"
        assert d["file_size"] == 512


# ╔══════════════════════════════════════════════════════════════════╗
# ║  ValidationProgress                                              ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestValidationProgress:
    """ValidationProgress tracks real-time validation state."""

    def test_is_complete_false_when_zero_total(self):
        """is_complete is False when total_bytes is 0 (unknown file size)."""
        p = ValidationProgress(bytes_processed=0, total_bytes=0)
        assert p.is_complete is False

    def test_is_complete_false_when_partial(self):
        p = ValidationProgress(bytes_processed=500, total_bytes=1000)
        assert p.is_complete is False

    def test_is_complete_true_when_all_processed(self):
        p = ValidationProgress(bytes_processed=1000, total_bytes=1000)
        assert p.is_complete is True

    def test_is_complete_true_when_overprocessed(self):
        """Edge case: bytes_processed may exceed total_bytes."""
        p = ValidationProgress(bytes_processed=1200, total_bytes=1000)
        assert p.is_complete is True


# ╔══════════════════════════════════════════════════════════════════╗
# ║  ValidationResult                                                ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestValidationResult:
    """ValidationResult aggregates a complete validation run."""

    @pytest.fixture
    def result_with_errors(self) -> ValidationResult:
        errors = [
            ValidationError(
                error_number=1,
                line=10,
                column=5,
                byte_offset=200,
                message="Tag mismatch",
                category=ErrorCategory.TAG_MISMATCH,
                severity=ErrorSeverity.ERROR,
            ),
            ValidationError(
                error_number=2,
                line=20,
                column=1,
                byte_offset=500,
                message="Invalid entity",
                category=ErrorCategory.INVALID_ENTITY,
                severity=ErrorSeverity.WARNING,
            ),
            ValidationError(
                error_number=3,
                line=30,
                column=1,
                byte_offset=800,
                message="Another tag mismatch",
                category=ErrorCategory.TAG_MISMATCH,
                severity=ErrorSeverity.ERROR,
            ),
        ]
        return ValidationResult(
            file_info=FileInfo(filename="test.xml", file_size=1000),
            errors=errors,
            start_time=datetime(2024, 1, 1, 12, 0, 0),
            end_time=datetime(2024, 1, 1, 12, 0, 5),
            duration_seconds=5.0,
        )

    @pytest.fixture
    def result_no_errors(self) -> ValidationResult:
        return ValidationResult(
            file_info=FileInfo(filename="clean.xml", file_size=500),
        )

    # ── Properties ──────────────────────────────────────────────────

    def test_error_count(self, result_with_errors: ValidationResult):
        assert result_with_errors.error_count == 3

    def test_error_count_zero(self, result_no_errors: ValidationResult):
        assert result_no_errors.error_count == 0

    def test_has_errors_true(self, result_with_errors: ValidationResult):
        assert result_with_errors.has_errors is True

    def test_has_errors_false(self, result_no_errors: ValidationResult):
        assert result_no_errors.has_errors is False

    # ── compute_summary ─────────────────────────────────────────────

    def test_compute_summary_totals(self, result_with_errors: ValidationResult):
        result_with_errors.compute_summary()
        stats = result_with_errors.summary_stats
        assert stats["total_errors"] == 3

    def test_compute_summary_by_severity(self, result_with_errors: ValidationResult):
        result_with_errors.compute_summary()
        by_sev = result_with_errors.summary_stats["by_severity"]
        assert by_sev["Error"] == 2
        assert by_sev["Warning"] == 1

    def test_compute_summary_by_category(self, result_with_errors: ValidationResult):
        result_with_errors.compute_summary()
        by_cat = result_with_errors.summary_stats["by_category"]
        assert by_cat["Tag Mismatch"] == 2
        assert by_cat["Invalid Entity"] == 1

    def test_compute_summary_empty(self, result_no_errors: ValidationResult):
        result_no_errors.compute_summary()
        stats = result_no_errors.summary_stats
        assert stats["total_errors"] == 0
        assert stats["by_severity"] == {}
        assert stats["by_category"] == {}

    # ── Serialization ───────────────────────────────────────────────

    def test_to_dict_keys(self, result_with_errors: ValidationResult):
        d = result_with_errors.to_dict()
        expected = {
            "file_info",
            "errors",
            "start_time",
            "end_time",
            "duration_seconds",
            "was_cancelled",
            "summary_stats",
        }
        assert set(d.keys()) == expected

    def test_to_dict_timestamps(self, result_with_errors: ValidationResult):
        d = result_with_errors.to_dict()
        assert d["start_time"] == "2024-01-01T12:00:00"
        assert d["end_time"] == "2024-01-01T12:00:05"

    def test_to_dict_none_timestamps(self, result_no_errors: ValidationResult):
        d = result_no_errors.to_dict()
        assert d["start_time"] is None
        assert d["end_time"] is None

    def test_to_json_is_valid_json(self, result_with_errors: ValidationResult):
        json_str = result_with_errors.to_json()
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        assert parsed["duration_seconds"] == 5.0

    def test_to_json_indent(self, result_no_errors: ValidationResult):
        json_str = result_no_errors.to_json(indent=4)
        # 4-space indent means lines will start with 4 spaces
        assert "    " in json_str

    def test_was_cancelled_default_false(self, result_no_errors: ValidationResult):
        assert result_no_errors.was_cancelled is False


# ╔══════════════════════════════════════════════════════════════════╗
# ║  AppSettings                                                     ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestAppSettings:
    """AppSettings manages persisted user preferences."""

    def test_defaults(self):
        s = AppSettings()
        assert s.context_line_count == 10
        assert s.theme == "dark"
        assert s.font_size == 12
        assert s.auto_open_last_file is False
        assert s.max_recent_files == 10
        assert s.recent_files == []

    # ── add_recent_file ─────────────────────────────────────────────

    def test_add_recent_file_basic(self):
        s = AppSettings()
        s.add_recent_file("/path/to/file.xml")
        assert s.recent_files == ["/path/to/file.xml"]

    def test_add_recent_file_ordering(self):
        """Most recently added file should be first."""
        s = AppSettings()
        s.add_recent_file("a.xml")
        s.add_recent_file("b.xml")
        s.add_recent_file("c.xml")
        assert s.recent_files == ["c.xml", "b.xml", "a.xml"]

    def test_add_recent_file_deduplication(self):
        """Re-adding a file moves it to front; no duplicates."""
        s = AppSettings()
        s.add_recent_file("a.xml")
        s.add_recent_file("b.xml")
        s.add_recent_file("a.xml")
        assert s.recent_files == ["a.xml", "b.xml"]

    def test_add_recent_file_respects_max_limit(self):
        """List is capped at max_recent_files."""
        s = AppSettings(max_recent_files=3)
        for i in range(5):
            s.add_recent_file(f"file_{i}.xml")
        assert len(s.recent_files) == 3
        # Most recent files should survive
        assert s.recent_files[0] == "file_4.xml"
        assert s.recent_files[1] == "file_3.xml"
        assert s.recent_files[2] == "file_2.xml"

    def test_add_recent_file_dedup_does_not_exceed_max(self):
        """Dedup + insert should not grow beyond max."""
        s = AppSettings(max_recent_files=2)
        s.add_recent_file("a.xml")
        s.add_recent_file("b.xml")
        s.add_recent_file("a.xml")  # move to front, still 2 items
        assert len(s.recent_files) == 2
        assert s.recent_files == ["a.xml", "b.xml"]

    # ── clear_recent_files ──────────────────────────────────────────

    def test_clear_recent_files(self):
        s = AppSettings()
        s.add_recent_file("a.xml")
        s.add_recent_file("b.xml")
        s.clear_recent_files()
        assert s.recent_files == []

    def test_clear_recent_files_when_empty(self):
        s = AppSettings()
        s.clear_recent_files()  # should not raise
        assert s.recent_files == []
