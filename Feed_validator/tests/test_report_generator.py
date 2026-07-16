"""
Tests for report generation (HTML, JSON, CSV, TXT).

The reports module is expected to expose:
    ``generate_report(result, output_path, format)``
or individual generators per format.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from validator.models import (
    ErrorCategory,
    ErrorSeverity,
    FileInfo,
    ValidationError,
    ValidationResult,
)
from reports.report_generator import generate_report


# ── Shared fixtures ─────────────────────────────────────────────────


@pytest.fixture
def result_with_errors() -> ValidationResult:
    """A ValidationResult containing 3 errors of varying severity."""
    errors = [
        ValidationError(
            error_number=1,
            line=5,
            column=10,
            byte_offset=100,
            message="Opening and ending tag mismatch: title vs author",
            category=ErrorCategory.TAG_MISMATCH,
            severity=ErrorSeverity.ERROR,
        ),
        ValidationError(
            error_number=2,
            line=12,
            column=25,
            byte_offset=350,
            message="Entity 'badentity' not defined",
            category=ErrorCategory.INVALID_ENTITY,
            severity=ErrorSeverity.WARNING,
        ),
        ValidationError(
            error_number=3,
            line=20,
            column=1,
            byte_offset=600,
            message="Premature end of data in tag root",
            category=ErrorCategory.UNEXPECTED_EOF,
            severity=ErrorSeverity.FATAL,
        ),
    ]
    r = ValidationResult(
        file_info=FileInfo(filename="test_report.xml", file_size=1024),
        errors=errors,
        duration_seconds=2.5,
    )
    r.compute_summary()
    return r


@pytest.fixture
def result_no_errors() -> ValidationResult:
    """A clean ValidationResult with zero errors."""
    r = ValidationResult(
        file_info=FileInfo(filename="clean.xml", file_size=512),
        duration_seconds=0.3,
    )
    r.compute_summary()
    return r


# ╔══════════════════════════════════════════════════════════════════╗
# ║  HTML reports                                                    ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestHtmlReport:
    """HTML report must contain key information and be valid-ish HTML."""

    def test_html_file_created(
        self, result_with_errors: ValidationResult, tmp_output_dir: Path
    ):
        out = tmp_output_dir / "report.html"
        generate_report(result_with_errors, out, format="html")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_html_contains_filename(
        self, result_with_errors: ValidationResult, tmp_output_dir: Path
    ):
        out = tmp_output_dir / "report.html"
        generate_report(result_with_errors, out, format="html")
        content = out.read_text(encoding="utf-8")
        assert "test_report.xml" in content

    def test_html_contains_error_count(
        self, result_with_errors: ValidationResult, tmp_output_dir: Path
    ):
        out = tmp_output_dir / "report.html"
        generate_report(result_with_errors, out, format="html")
        content = out.read_text(encoding="utf-8")
        assert "3" in content  # total errors

    def test_html_valid_xml_report(
        self, result_no_errors: ValidationResult, tmp_output_dir: Path
    ):
        """Report for a valid file should still be generated."""
        out = tmp_output_dir / "clean_report.html"
        generate_report(result_no_errors, out, format="html")
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "clean.xml" in content


# ╔══════════════════════════════════════════════════════════════════╗
# ║  JSON reports                                                    ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestJsonReport:
    """JSON reports must be valid JSON with all expected fields."""

    def test_json_file_created(
        self, result_with_errors: ValidationResult, tmp_output_dir: Path
    ):
        out = tmp_output_dir / "report.json"
        generate_report(result_with_errors, out, format="json")
        assert out.exists()

    def test_json_is_parseable(
        self, result_with_errors: ValidationResult, tmp_output_dir: Path
    ):
        out = tmp_output_dir / "report.json"
        generate_report(result_with_errors, out, format="json")
        data = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_json_contains_all_fields(
        self, result_with_errors: ValidationResult, tmp_output_dir: Path
    ):
        out = tmp_output_dir / "report.json"
        generate_report(result_with_errors, out, format="json")
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "file_info" in data
        assert "errors" in data
        assert "duration_seconds" in data

    def test_json_error_count_matches(
        self, result_with_errors: ValidationResult, tmp_output_dir: Path
    ):
        out = tmp_output_dir / "report.json"
        generate_report(result_with_errors, out, format="json")
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data["errors"]) == 3

    def test_json_no_errors(
        self, result_no_errors: ValidationResult, tmp_output_dir: Path
    ):
        out = tmp_output_dir / "report.json"
        generate_report(result_no_errors, out, format="json")
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data["errors"]) == 0


# ╔══════════════════════════════════════════════════════════════════╗
# ║  CSV reports                                                     ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestCsvReport:
    """CSV reports must have correct headers and row counts."""

    def test_csv_file_created(
        self, result_with_errors: ValidationResult, tmp_output_dir: Path
    ):
        out = tmp_output_dir / "report.csv"
        generate_report(result_with_errors, out, format="csv")
        assert out.exists()

    def test_csv_headers(
        self, result_with_errors: ValidationResult, tmp_output_dir: Path
    ):
        out = tmp_output_dir / "report.csv"
        generate_report(result_with_errors, out, format="csv")
        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)
        # Expect at least these columns
        for expected_col in ("line", "column", "message", "category", "severity"):
            assert expected_col.lower() in [h.lower() for h in headers], (
                f"Missing expected CSV header: {expected_col}"
            )

    def test_csv_row_count_matches_errors(
        self, result_with_errors: ValidationResult, tmp_output_dir: Path
    ):
        out = tmp_output_dir / "report.csv"
        generate_report(result_with_errors, out, format="csv")
        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            rows = list(reader)
        assert len(rows) == 3

    def test_csv_no_errors_only_header(
        self, result_no_errors: ValidationResult, tmp_output_dir: Path
    ):
        out = tmp_output_dir / "report.csv"
        generate_report(result_no_errors, out, format="csv")
        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        # Should have header row only (or header + 0 data rows)
        assert len(rows) <= 1 or (len(rows) == 1)


# ╔══════════════════════════════════════════════════════════════════╗
# ║  TXT reports                                                     ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestTxtReport:
    """TXT (plain text) reports must contain human-readable error details."""

    def test_txt_file_created(
        self, result_with_errors: ValidationResult, tmp_output_dir: Path
    ):
        out = tmp_output_dir / "report.txt"
        generate_report(result_with_errors, out, format="txt")
        assert out.exists()

    def test_txt_contains_filename(
        self, result_with_errors: ValidationResult, tmp_output_dir: Path
    ):
        out = tmp_output_dir / "report.txt"
        generate_report(result_with_errors, out, format="txt")
        content = out.read_text(encoding="utf-8")
        assert "test_report.xml" in content

    def test_txt_contains_error_messages(
        self, result_with_errors: ValidationResult, tmp_output_dir: Path
    ):
        out = tmp_output_dir / "report.txt"
        generate_report(result_with_errors, out, format="txt")
        content = out.read_text(encoding="utf-8")
        assert "tag mismatch" in content.lower() or "Tag Mismatch" in content

    def test_txt_contains_line_numbers(
        self, result_with_errors: ValidationResult, tmp_output_dir: Path
    ):
        out = tmp_output_dir / "report.txt"
        generate_report(result_with_errors, out, format="txt")
        content = out.read_text(encoding="utf-8")
        # Errors are on lines 5, 12, 20
        assert "5" in content
        assert "12" in content

    def test_txt_no_errors(
        self, result_no_errors: ValidationResult, tmp_output_dir: Path
    ):
        out = tmp_output_dir / "report.txt"
        generate_report(result_no_errors, out, format="txt")
        content = out.read_text(encoding="utf-8")
        assert "clean.xml" in content
