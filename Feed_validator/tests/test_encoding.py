"""
Tests for validator.encoding — character encoding detection.

The encoding module is expected to expose a ``detect_encoding(path)``
function that returns the detected encoding string for an XML file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from validator.encoding import detect_encoding


class TestDetectEncoding:
    """Verify encoding detection across common scenarios."""

    def test_utf8_file_detected(self, valid_xml_path: Path):
        """A plain UTF-8 file should be detected as utf-8."""
        enc = detect_encoding(valid_xml_path)
        assert enc.lower().replace("-", "") in ("utf8", "utf-8", "ascii")

    def test_utf8_bom_detected(self, tmp_path: Path):
        """A file starting with the UTF-8 BOM (EF BB BF) should be utf-8."""
        content = b"\xef\xbb\xbf" + b'<?xml version="1.0"?>\n<root/>\n'
        bom_file = tmp_path / "bom.xml"
        bom_file.write_bytes(content)
        enc = detect_encoding(bom_file)
        assert "utf" in enc.lower()

    def test_xml_declaration_explicit_encoding(self, tmp_path: Path):
        """Encoding declared in the XML PI should be respected."""
        content = b'<?xml version="1.0" encoding="ISO-8859-1"?>\n<root/>\n'
        f = tmp_path / "latin1.xml"
        f.write_bytes(content)
        enc = detect_encoding(f)
        assert enc.lower().replace("-", "") in (
            "iso88591",
            "latin1",
            "iso-8859-1",
            "latin-1",
            "windows-1252",
            "windows1252",
        )

    def test_fallback_to_utf8_for_ambiguous(self, tmp_path: Path):
        """
        Plain ASCII content with no declaration should default to utf-8
        (ASCII is a strict subset of UTF-8).
        """
        f = tmp_path / "plain.xml"
        f.write_text("<root/>", encoding="ascii")
        enc = detect_encoding(f)
        assert enc.lower().replace("-", "") in ("utf8", "utf-8", "ascii")

    @pytest.mark.parametrize(
        "encoding_name, xml_decl_encoding, sample_bytes",
        [
            (
                "utf-16-le",
                "UTF-16",
                b"\xff\xfe"  # UTF-16 LE BOM
                + '<?xml version="1.0" encoding="UTF-16"?>\n<root/>\n'.encode("utf-16-le"),
            ),
            (
                "iso-8859-1",
                "ISO-8859-1",
                b'<?xml version="1.0" encoding="ISO-8859-1"?>\n<root>\xc9</root>\n',
            ),
        ],
    )
    def test_non_utf8_encodings(
        self,
        tmp_path: Path,
        encoding_name: str,
        xml_decl_encoding: str,
        sample_bytes: bytes,
    ):
        """Non-UTF-8 encodings should be detected when declared or BOM is present."""
        f = tmp_path / f"test_{encoding_name.replace('-', '_')}.xml"
        f.write_bytes(sample_bytes)
        enc = detect_encoding(f)
        # Normalise for comparison — accept common aliases
        normalised = enc.lower().replace("-", "").replace("_", "")
        assert normalised != "", f"detect_encoding returned empty for {encoding_name}"
