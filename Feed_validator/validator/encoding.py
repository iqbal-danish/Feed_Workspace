"""
Encoding detection for XML files.

Implements a multi-strategy approach:
1. Byte-Order Mark (BOM) detection
2. XML declaration parsing
3. Statistical analysis via *charset-normalizer*
4. UTF-8 fallback
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger("xml_validator_pro.encoding")

# ── BOM signatures (longest-first so UTF-32 is checked before UTF-16) ───
_BOM_TABLE: list[tuple[bytes, str]] = [
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
]

# Regex that matches  encoding="..." or encoding='...'  in an XML declaration.
_XML_DECL_ENCODING_RE = re.compile(
    rb"""<\?xml[^?]*\bencoding\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)

_SAMPLE_SIZE = 65_536  # 64 KB — enough for charset-normalizer heuristics


class EncodingDetector:
    """Detect the character encoding of an XML file.

    The detection strategy is applied in order of reliability:

    1. **BOM** — if the file starts with a known byte-order mark the
       corresponding codec is returned immediately.
    2. **XML declaration** — the ``encoding`` pseudo-attribute of
       ``<?xml … ?>`` is extracted when present.
    3. **charset-normalizer** — statistical analysis of the first
       64 KB of file content.
    4. **Fallback** — ``'utf-8'`` is assumed when all other methods
       are inconclusive.
    """

    def detect(self, file_path: Path) -> str:
        """Detect the encoding of the file at *file_path*.

        Args:
            file_path: Path to an XML file on disk.

        Returns:
            A Python codec name suitable for :func:`open` or
            :meth:`bytes.decode`.
        """
        logger.info("Detecting encoding for %s", file_path.name)

        # -- 1. BOM check ---------------------------------------------------
        encoding = self._detect_bom(file_path)
        if encoding:
            logger.info("Encoding detected via BOM: %s", encoding)
            return encoding

        # -- 2. XML declaration ---------------------------------------------
        encoding = self._detect_xml_declaration(file_path)
        if encoding:
            logger.info("Encoding detected via XML declaration: %s", encoding)
            return encoding

        # -- 3. charset-normalizer ------------------------------------------
        encoding = self._detect_charset_normalizer(file_path)
        if encoding:
            logger.info("Encoding detected via charset-normalizer: %s", encoding)
            return encoding

        # -- 4. Fallback ----------------------------------------------------
        logger.info("Falling back to utf-8")
        return "utf-8"

    # ── Private helpers ───────────────────────────────────────────────────

    @staticmethod
    def _detect_bom(file_path: Path) -> str | None:
        """Return codec name if a BOM is found, else *None*."""
        try:
            with open(file_path, "rb") as fh:
                raw = fh.read(4)
        except OSError as exc:
            logger.warning("Cannot read BOM from %s: %s", file_path, exc)
            return None

        for bom_bytes, codec in _BOM_TABLE:
            if raw.startswith(bom_bytes):
                return codec
        return None

    @staticmethod
    def _detect_xml_declaration(file_path: Path) -> str | None:
        """Parse ``<?xml … encoding="…" ?>`` from the start of the file."""
        try:
            with open(file_path, "rb") as fh:
                head = fh.read(256)
        except OSError as exc:
            logger.warning(
                "Cannot read XML declaration from %s: %s", file_path, exc
            )
            return None

        match = _XML_DECL_ENCODING_RE.search(head)
        if match:
            declared = match.group(1).decode("ascii", errors="replace").strip()
            logger.debug("XML declaration declares encoding=%r", declared)
            return declared.lower()
        return None

    @staticmethod
    def _detect_charset_normalizer(file_path: Path) -> str | None:
        """Use *charset-normalizer* to guess the encoding statistically."""
        try:
            from charset_normalizer import from_path

            results = from_path(file_path, cp_isolation=None, explain=False)
            best = results.best()
            if best is not None:
                encoding = best.encoding
                logger.debug(
                    "charset-normalizer best match: %s (confidence=%.2f)",
                    encoding,
                    best.encoding,  # charset-normalizer ≥3 exposes .encoding
                )
                return encoding
        except ImportError:
            logger.warning(
                "charset-normalizer is not installed; skipping statistical detection"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("charset-normalizer failed: %s", exc)

        return None


def detect_encoding(file_path: Path) -> str:
    """Convenience function to detect encoding."""
    return EncodingDetector().detect(file_path)

