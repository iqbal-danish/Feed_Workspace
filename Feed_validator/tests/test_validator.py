"""
Tests for the full XML validation pipeline.

The validator module is expected to expose ``validate_xml(path, **kwargs)``
which returns a ``ValidationResult``.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from validator.models import (
    ErrorCategory,
    FileInfo,
    ValidationResult,
)
from validator.xml_validator import validate_xml


class TestValidXmlFiles:
    """Well-formed XML must produce zero errors."""

    def test_valid_small_no_errors(self, valid_xml_path: Path):
        result = validate_xml(valid_xml_path)
        assert isinstance(result, ValidationResult)
        assert result.error_count == 0
        assert result.has_errors is False

    def test_valid_namespaces_no_errors(self, valid_ns_xml_path: Path):
        result = validate_xml(valid_ns_xml_path)
        assert result.error_count == 0

    def test_valid_namespaces_detected_count(self, valid_ns_xml_path: Path):
        """The validator should count at least 3 distinct namespaces."""
        result = validate_xml(valid_ns_xml_path)
        assert result.file_info.namespace_count >= 3


class TestMalformedXmlDetection:
    """Each malformed fixture should produce at least one categorised error."""

    def test_tag_mismatch_detected(self, malformed_tag_path: Path):
        result = validate_xml(malformed_tag_path)
        assert result.has_errors
        categories = {e.category for e in result.errors}
        assert ErrorCategory.TAG_MISMATCH in categories

    def test_invalid_entity_detected(self, malformed_entity_path: Path):
        result = validate_xml(malformed_entity_path)
        assert result.has_errors
        categories = {e.category for e in result.errors}
        assert ErrorCategory.INVALID_ENTITY in categories

    def test_malformed_cdata_detected(self, malformed_cdata_path: Path):
        result = validate_xml(malformed_cdata_path)
        assert result.has_errors
        # CDATA issues may also surface as UNEXPECTED_EOF; accept either
        categories = {e.category for e in result.errors}
        assert categories & {ErrorCategory.MALFORMED_CDATA, ErrorCategory.UNEXPECTED_EOF}

    def test_duplicate_declaration_detected(self, malformed_duplicate_decl_path: Path):
        result = validate_xml(malformed_duplicate_decl_path)
        assert result.has_errors
        categories = {e.category for e in result.errors}
        assert categories & {
            ErrorCategory.DUPLICATE_DECLARATION,
            ErrorCategory.MALFORMED_XML,
        }


class TestFileInfoPopulation:
    """validate_xml must populate FileInfo with accurate metadata."""

    def test_filename_is_set(self, valid_xml_path: Path):
        result = validate_xml(valid_xml_path)
        assert result.file_info.filename == valid_xml_path.name

    def test_file_size_is_positive(self, valid_xml_path: Path):
        result = validate_xml(valid_xml_path)
        assert result.file_info.file_size > 0

    def test_encoding_is_set(self, valid_xml_path: Path):
        result = validate_xml(valid_xml_path)
        assert result.file_info.encoding != ""

    def test_root_element_detected(self, valid_xml_path: Path):
        result = validate_xml(valid_xml_path)
        assert result.file_info.root_element == "catalog"


class TestEdgeCases:
    """Boundary conditions and special scenarios."""

    def test_nonexistent_file_raises(self, tmp_path: Path):
        fake = tmp_path / "does_not_exist.xml"
        with pytest.raises((FileNotFoundError, OSError)):
            validate_xml(fake)

    def test_empty_file_handling(self, tmp_xml_file):
        """An empty file should either raise or return errors — never hang."""
        empty = tmp_xml_file("", filename="empty.xml")
        result = validate_xml(empty)
        # Empty XML is not well-formed; expect at least one error
        assert result.has_errors

    def test_minimal_valid_xml(self, tmp_xml_file):
        """Smallest possible well-formed XML."""
        path = tmp_xml_file("<r/>")
        result = validate_xml(path)
        assert result.error_count == 0

    def test_xml_with_comments(self, tmp_xml_file):
        content = (
            '<?xml version="1.0"?>\n'
            "<!-- This is a comment -->\n"
            "<root><!-- inner --></root>\n"
        )
        path = tmp_xml_file(content)
        result = validate_xml(path)
        assert result.error_count == 0


class TestCancellation:
    """Validation on a large file can be cancelled mid-stream."""

    def test_cancel_sets_was_cancelled(self, large_xml_file: Path):
        """
        Start validation in a thread, cancel almost immediately, and
        confirm was_cancelled is True in the result.
        """
        cancel_event = threading.Event()
        result_holder: list[ValidationResult] = []

        def run():
            r = validate_xml(large_xml_file, cancel_event=cancel_event)
            result_holder.append(r)

        t = threading.Thread(target=run)
        t.start()
        # Give the thread a moment to start, then cancel
        cancel_event.set()
        t.join(timeout=10)

        assert len(result_holder) == 1
        assert result_holder[0].was_cancelled is True
