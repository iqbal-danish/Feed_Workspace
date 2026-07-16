"""
Shared pytest fixtures for XML Validator Pro test suite.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# ── Fixture directory ───────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── XML file path fixtures ──────────────────────────────────────────

@pytest.fixture
def valid_xml_path() -> Path:
    """Path to a small, well-formed XML file with 3 <book> elements."""
    return FIXTURES_DIR / "valid_small.xml"


@pytest.fixture
def valid_ns_xml_path() -> Path:
    """Path to a valid XML file with 3 different namespace declarations."""
    return FIXTURES_DIR / "valid_with_namespaces.xml"


@pytest.fixture
def malformed_tag_path() -> Path:
    """Path to XML with mismatched opening/closing tags."""
    return FIXTURES_DIR / "malformed_tag_mismatch.xml"


@pytest.fixture
def malformed_entity_path() -> Path:
    """Path to XML with an undefined entity reference (&badentity;)."""
    return FIXTURES_DIR / "malformed_invalid_entity.xml"


@pytest.fixture
def malformed_cdata_path() -> Path:
    """Path to XML with an unclosed CDATA section."""
    return FIXTURES_DIR / "malformed_cdata.xml"


@pytest.fixture
def malformed_duplicate_decl_path() -> Path:
    """Path to XML with two <?xml ...?> processing instructions."""
    return FIXTURES_DIR / "malformed_duplicate_declaration.xml"


@pytest.fixture
def malformed_illegal_chars_path(tmp_path: Path) -> Path:
    """
    Generates an XML file containing illegal control characters at runtime.

    Raw control characters (like \\x0B, \\x02) are problematic to store in
    text files, so we create this fixture dynamically.
    """
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<catalog>\n"
        "    <book id=\"1\">\n"
        "        <title>Illegal Chars</title>\n"
        "        <description>Contains illegal char: \x0b and \x02</description>\n"
        "    </book>\n"
        "</catalog>\n"
    )
    file_path = tmp_path / "malformed_illegal_chars.xml"
    file_path.write_bytes(content.encode("utf-8"))
    return file_path


@pytest.fixture
def malformed_bad_encoding_path(tmp_path: Path) -> Path:
    """
    Generates an XML file declaring UTF-8 but containing raw latin-1 bytes.

    The é (0xE9) and ü (0xFC) bytes are invalid standalone UTF-8 sequences,
    producing an encoding mismatch the validator should detect.
    """
    header = b'<?xml version="1.0" encoding="UTF-8"?>\n'
    body = (
        b"<catalog>\n"
        b'    <book id="1">\n'
        b"        <title>Encoding Test</title>\n"
        b"        <author>Ren\xe9 M\xfcller</author>\n"
        b"    </book>\n"
        b"</catalog>\n"
    )
    file_path = tmp_path / "malformed_bad_encoding.xml"
    file_path.write_bytes(header + body)
    return file_path


# ── Temporary file helpers ──────────────────────────────────────────

@pytest.fixture
def tmp_xml_file(tmp_path: Path):
    """
    Factory fixture that writes arbitrary XML content to a temp file.

    Usage::

        def test_something(tmp_xml_file):
            path = tmp_xml_file('<root><child/></root>')
            ...
    """
    def _create(content: str, filename: str = "test.xml") -> Path:
        file_path = tmp_path / filename
        file_path.write_text(content, encoding="utf-8")
        return file_path

    return _create


@pytest.fixture
def large_xml_file(tmp_path: Path) -> Path:
    """
    Creates a ~1 MB well-formed XML file with many repeated <item> elements.

    Useful for testing streaming performance and memory efficiency.
    """
    file_path = tmp_path / "large.xml"

    # Each <item> block is ~120 bytes; ~8500 items ≈ 1 MB
    with open(file_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write("<catalog>\n")
        for i in range(8500):
            f.write(
                f'    <item id="{i}">\n'
                f"        <name>Item {i:05d}</name>\n"
                f"        <value>{i * 1.23:.2f}</value>\n"
                f"    </item>\n"
            )
        f.write("</catalog>\n")

    # Sanity-check the file is roughly 1 MB
    actual_size = file_path.stat().st_size
    assert actual_size > 800_000, f"Large XML fixture too small: {actual_size}"
    return file_path


@pytest.fixture
def tmp_output_dir(tmp_path: Path) -> Path:
    """Temporary directory for report output files."""
    output_dir = tmp_path / "reports"
    output_dir.mkdir()
    return output_dir
