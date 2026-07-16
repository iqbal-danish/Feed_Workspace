"""
Tests for the streaming XML validator.

The streaming validator is expected to expose:
    ``StreamingXmlValidator(path, progress_callback, error_callback)``
with a ``.validate()`` method.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from validator.models import ValidationError, ValidationProgress
from validator.streaming_validator import StreamingXmlValidator


class TestProgressCallback:
    """The progress callback must be invoked with monotonically increasing bytes."""

    def test_progress_bytes_increase(self, valid_xml_path: Path):
        progress_snapshots: list[ValidationProgress] = []

        def on_progress(p: ValidationProgress) -> None:
            progress_snapshots.append(
                ValidationProgress(
                    bytes_processed=p.bytes_processed,
                    total_bytes=p.total_bytes,
                )
            )

        sv = StreamingXmlValidator(
            path=valid_xml_path,
            progress_callback=on_progress,
        )
        sv.validate()

        assert len(progress_snapshots) >= 1, "Progress callback was never invoked"
        # bytes_processed should be non-decreasing
        for i in range(1, len(progress_snapshots)):
            assert (
                progress_snapshots[i].bytes_processed
                >= progress_snapshots[i - 1].bytes_processed
            ), "bytes_processed decreased between progress callbacks"

    def test_final_progress_matches_file_size(self, valid_xml_path: Path):
        """Last progress snapshot's bytes_processed should equal total_bytes."""
        last_progress: list[ValidationProgress] = []

        def on_progress(p: ValidationProgress) -> None:
            last_progress.clear()
            last_progress.append(p)

        sv = StreamingXmlValidator(
            path=valid_xml_path,
            progress_callback=on_progress,
        )
        sv.validate()

        assert len(last_progress) == 1
        lp = last_progress[0]
        assert lp.bytes_processed >= lp.total_bytes


class TestErrorCallback:
    """Error callback must fire once per detected error."""

    def test_error_callback_invoked_for_malformed(self, malformed_tag_path: Path):
        errors_received: list[ValidationError] = []

        def on_error(e: ValidationError) -> None:
            errors_received.append(e)

        sv = StreamingXmlValidator(
            path=malformed_tag_path,
            error_callback=on_error,
        )
        sv.validate()

        assert len(errors_received) >= 1, "Error callback was never called"

    def test_no_error_callback_for_valid(self, valid_xml_path: Path):
        errors_received: list[ValidationError] = []

        def on_error(e: ValidationError) -> None:
            errors_received.append(e)

        sv = StreamingXmlValidator(
            path=valid_xml_path,
            error_callback=on_error,
        )
        sv.validate()

        assert len(errors_received) == 0


class TestContextLinesExtraction:
    """Error objects should contain surrounding context lines."""

    def test_context_lines_present(self, malformed_tag_path: Path):
        errors_received: list[ValidationError] = []

        def on_error(e: ValidationError) -> None:
            errors_received.append(e)

        sv = StreamingXmlValidator(
            path=malformed_tag_path,
            error_callback=on_error,
        )
        sv.validate()

        assert len(errors_received) >= 1
        err = errors_received[0]
        assert len(err.context_lines) > 0, "No context lines extracted"

    def test_context_lines_include_error_line(self, malformed_tag_path: Path):
        """At least one context line should have is_error_line == True."""
        errors_received: list[ValidationError] = []

        def on_error(e: ValidationError) -> None:
            errors_received.append(e)

        sv = StreamingXmlValidator(
            path=malformed_tag_path,
            error_callback=on_error,
        )
        sv.validate()

        assert len(errors_received) >= 1
        err = errors_received[0]
        error_flags = [cl.is_error_line for cl in err.context_lines]
        assert any(error_flags), "No context line marked as is_error_line"


class TestStreamingMemoryEfficiency:
    """Streaming validation of large files must complete without issues."""

    def test_large_file_completes(self, large_xml_file: Path):
        """Validate a ~1 MB file and confirm it completes with zero errors."""
        progress_count = 0

        def on_progress(p: ValidationProgress) -> None:
            nonlocal progress_count
            progress_count += 1

        sv = StreamingXmlValidator(
            path=large_xml_file,
            progress_callback=on_progress,
        )
        result = sv.validate()

        assert result.error_count == 0
        assert progress_count >= 1, "Progress callback should fire for large files"

    def test_large_file_multiple_progress_reports(self, large_xml_file: Path):
        """A 1 MB file should produce more than one progress callback."""
        progress_count = 0

        def on_progress(p: ValidationProgress) -> None:
            nonlocal progress_count
            progress_count += 1

        sv = StreamingXmlValidator(
            path=large_xml_file,
            progress_callback=on_progress,
        )
        sv.validate()

        assert progress_count > 1, (
            f"Expected multiple progress reports for ~1 MB file, got {progress_count}"
        )


class TestMinifiedContext:
    """Test context lines extraction for minified documents."""

    def test_minified_xml_context(self, tmp_path: Path):
        content = "<root>" + "<child>data</child>" * 300 + "<badtag>mismatch</othertag></root>"
        f = tmp_path / "minified.xml"
        f.write_text(content, encoding="utf-8")

        from validator.streaming_validator import StreamingValidator
        sv = StreamingValidator()
        result = sv.validate(f)

        assert result.error_count > 0
        err = result.errors[0]
        assert len(err.context_lines) > 0
        assert any(cl.is_error_line for cl in err.context_lines)
        # Verify it pretty printed/split
        assert len(err.context_lines) > 1


class TestUrlDownloadAndDetection:
    """Test URL downloading support and type auto-detection."""

    def test_type_detection(self, tmp_path: Path):
        from validator.streaming_validator import StreamingValidator
        sv = StreamingValidator()

        # XML
        f1 = tmp_path / "test1.xml"
        f1.write_text("<root></root>")
        assert sv._detect_file_type(f1) == "xml"

        # JSON
        f2 = tmp_path / "test2.json"
        f2.write_text("{}")
        assert sv._detect_file_type(f2) == "json"

        # Ambiguous XML with peek
        f3 = tmp_path / "test3.txt"
        f3.write_text("   <some_xml />")
        assert sv._detect_file_type(f3) == "xml"

        # Ambiguous JSON with peek
        f4 = tmp_path / "test4.txt"
        f4.write_text("   [ 1, 2 ]")
        assert sv._detect_file_type(f4) == "json"

