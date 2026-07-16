"""
Tests for the JSON streaming validator.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from validator.json_validator import StreamingJSONParser
from validator.models import ErrorCategory, ValidationError, ValidationProgress, FileInfo


class TestJSONValidator:
    """Tests for validating JSON documents streamingly."""

    def test_valid_json_no_errors(self, tmp_path: Path):
        """A simple well-formed JSON document should validate with 0 errors."""
        content = '{"name": "XML Validator Pro", "version": 1.0, "tags": ["fast", "light"]}'
        f = tmp_path / "valid.json"
        f.write_text(content, encoding="utf-8")

        parser = StreamingJSONParser()
        errors, file_info = parser.parse(f)

        assert len(errors) == 0
        assert file_info.filename == "valid.json"
        assert file_info.root_element == "object"

    def test_valid_json_array_no_errors(self, tmp_path: Path):
        """A well-formed JSON array should validate successfully."""
        content = '[1, 2, "three", {"four": 4}]'
        f = tmp_path / "array.json"
        f.write_text(content, encoding="utf-8")

        parser = StreamingJSONParser()
        errors, file_info = parser.parse(f)

        assert len(errors) == 0
        assert file_info.root_element == "array"

    @pytest.mark.parametrize(
        "json_content, expected_message_part, expected_category",
        [
            ('{"key": "value"', "Unclosed structure", ErrorCategory.TAG_MISMATCH),
            ('{"key": "value",}', "Trailing comma inside object", ErrorCategory.INVALID_ATTRIBUTE),
            ('{"key": "val" "key2": "val"}', "Expected ',' or '}'", ErrorCategory.TAG_MISMATCH),
            ('{"key": "val", "key": "val2"}', "Duplicate object key", ErrorCategory.INVALID_ATTRIBUTE),
            ('{"key": value}', "Invalid token 'value'", ErrorCategory.MALFORMED_XML),
            ('[1, 2, ]', "Trailing comma inside array", ErrorCategory.INVALID_ATTRIBUTE),
        ],
    )
    def test_invalid_json_detected(
        self, tmp_path: Path, json_content: str, expected_message_part: str, expected_category: ErrorCategory
    ):
        """Common JSON syntax errors must be caught with appropriate categories."""
        f = tmp_path / "invalid.json"
        f.write_text(json_content, encoding="utf-8")

        parser = StreamingJSONParser()
        errors, _ = parser.parse(f)

        assert len(errors) > 0
        err = errors[0]
        assert expected_message_part.lower() in err.message.lower()

    def test_json_lines_progress_callback(self, tmp_path: Path):
        """Progress callback should be invoked while reading the JSON file."""
        f = tmp_path / "large_lines.json"
        items = ['{"item": 1}'] * 5000
        content = ",\n".join(items)
        f.write_text(f"[\n{content}\n]", encoding="utf-8")

        progress_calls = []

        def on_progress(bytes_read: int, total: int):
            progress_calls.append((bytes_read, total))

        parser = StreamingJSONParser()
        errors, _ = parser.parse(f, progress_callback=on_progress)

        assert len(errors) == 0
        assert len(progress_calls) >= 1
