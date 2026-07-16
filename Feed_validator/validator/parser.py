"""
Streaming XML parser for XML Validator Pro.

Provides incremental, memory-efficient XML parsing using lxml's
feed-parser interface.  Supports progress reporting, cancellation,
and contextual error extraction.
"""

from __future__ import annotations

import io
import logging
import threading
from collections.abc import Callable
from pathlib import Path

from lxml import etree

from validator.models import (
    ContextLine,
    ErrorCategory,
    ErrorSeverity,
    FileInfo,
    ValidationError,
)

logger = logging.getLogger("xml_validator_pro.parser")

_CHUNK_SIZE = 65_536  # 64 KB


# ─────────────────────────────────────────────────────────────────────────
# Progress wrapper
# ─────────────────────────────────────────────────────────────────────────

class ProgressFileWrapper:
    """Wraps a binary file object and tracks the number of bytes read.

    Used as a transparent proxy so the parser can consume the file
    normally while the caller inspects :pyattr:`bytes_read` and
    :pyattr:`total_size` for progress calculation.
    """

    def __init__(
        self,
        file_obj: io.RawIOBase | io.BufferedIOBase,
        total_size: int,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> None:
        self._file = file_obj
        self._bytes_read: int = 0
        self._total_size: int = total_size
        self._progress_callback = progress_callback

    # -- Public API --------------------------------------------------------

    @property
    def bytes_read(self) -> int:
        """Number of bytes consumed so far."""
        return self._bytes_read

    @property
    def total_size(self) -> int:
        """Total file size in bytes."""
        return self._total_size

    def read(self, size: int = -1) -> bytes:
        """Read up to *size* bytes and record progress."""
        data = self._file.read(size)
        self._bytes_read += len(data)
        if self._progress_callback is not None:
            self._progress_callback(self._bytes_read, self._total_size)
        return data

    def close(self) -> None:
        """Close the underlying file."""
        self._file.close()


# ─────────────────────────────────────────────────────────────────────────
# Error categorisation
# ─────────────────────────────────────────────────────────────────────────

def categorize_error(message: str) -> ErrorCategory:
    """Map an lxml error message to an :class:`ErrorCategory`.

    The matching is intentionally broad so that minor wording changes
    between lxml versions are tolerated.

    Args:
        message: The error string emitted by lxml's error log.

    Returns:
        The best-matching :class:`ErrorCategory`.
    """
    msg = message  # keep original case for mixed-case keywords

    # Order matters — more specific patterns before generic ones.
    if "tag mismatch" in msg or "Opening and ending" in msg:
        return ErrorCategory.TAG_MISMATCH

    if "encoding" in msg.lower() or "UTF" in msg:
        return ErrorCategory.INVALID_ENCODING

    if "Entity" in msg or "entity" in msg:
        return ErrorCategory.INVALID_ENTITY

    if "CDATA" in msg:
        return ErrorCategory.MALFORMED_CDATA

    if "EOF" in msg or "Premature end" in msg or "Extra content at the end" in msg:
        return ErrorCategory.UNEXPECTED_EOF

    if "XML declaration" in msg and "allowed only" in msg:
        return ErrorCategory.DUPLICATE_DECLARATION

    if "Namespace" in msg or "namespace" in msg:
        return ErrorCategory.NAMESPACE_ERROR

    if "xmlChar" in msg or "invalid character" in msg.lower() or "illegal" in msg.lower():
        return ErrorCategory.ILLEGAL_CHARACTER

    if "attribute" in msg.lower():
        return ErrorCategory.INVALID_ATTRIBUTE

    return ErrorCategory.MALFORMED_XML


def extract_tag_info(message: str, category: "ErrorCategory") -> tuple[str, str, int]:
    """Parse an lxml error message to extract structured tag information.

    Returns:
        A 3-tuple of ``(tag_name, reference_tag, reference_line)`` where:
        - *tag_name*      is the problematic field/tag name (e.g. ``"job"``)
        - *reference_tag* is the mismatched partner tag (e.g. ``"jobs"``) or ``""``
        - *reference_line* is the line where the partner/opening tag was (0 = unknown)
    """
    import re

    # Pattern: "Opening and ending tag mismatch: {open_tag} line {n} and {close_tag}"
    # lxml puts the *closing* tag after "and" and the *opening* tag before "line"
    m = re.search(
        r'Opening and ending tag mismatch:\s+(\S+)\s+line\s+(\d+)\s+and\s+(\S+)',
        message,
    )
    if m:
        # open_tag is on m.group(1) at m.group(2), close_tag is m.group(3)
        open_tag   = m.group(1)
        ref_line   = int(m.group(2))
        close_tag  = m.group(3)
        # The "current" error is at the closing tag; show closing tag as tag_name
        return close_tag, open_tag, ref_line

    # Pattern: "Tag {name} was not closed"
    m = re.search(r"Tag\s+(\S+)\s+was not closed", message)
    if m:
        return m.group(1), "", 0

    # Pattern: "EndTag: '</' not found" — no tag name available
    if "EndTag" in message and "not found" in message:
        return "", "", 0

    # Pattern: "Entity '{name}' not defined" or "undefined entity &name;"
    m = re.search(r"Entity\s+'([^']+)'", message)
    if m:
        return m.group(1), "", 0
    m = re.search(r"undefined entity\s+&([^;]+);", message, re.IGNORECASE)
    if m:
        return m.group(1), "", 0

    # Pattern: "Attribute {name} redefined" or "duplicate attribute"
    m = re.search(r"Attribute\s+(\S+)\s+redefined", message)
    if m:
        return m.group(1), "", 0

    # Pattern: namespace prefix "use of undefined namespace prefix: {prefix}"
    m = re.search(r"namespace prefix[:\s]+['\"]?([\w]+)['\"]?", message, re.IGNORECASE)
    if m:
        return m.group(1), "", 0

    # Pattern: "Char 0x{hex} out of allowed range" / "xmlChar 0x{hex}"
    m = re.search(r"(?:xmlChar|Char)\s+0x([0-9A-Fa-f]+)", message)
    if m:
        return f"U+{m.group(1).upper()}", "", 0

    return "", "", 0


# ─────────────────────────────────────────────────────────────────────────
# Context extraction
# ─────────────────────────────────────────────────────────────────────────

def extract_context_lines(
    file_path: Path,
    error_line: int,
    context_count: int = 10,
    encoding: str = "utf-8",
    byte_offset: int = 0,
) -> list[ContextLine]:
    """Read lines surrounding *error_line* from the file.

    For minified files, extracts a byte range around *byte_offset* and pretty-prints it
    to avoid memory crashes. For standard files, extracts surrounding lines.
    """
    if error_line < 1:
        return []

    # Detect if file is minified (first 2048 bytes have no newlines)
    is_minified = False
    try:
        with open(file_path, "rb") as f:
            peek = f.read(2048)
            if len(peek) == 2048 and b"\n" not in peek:
                is_minified = True
    except Exception:
        pass

    if is_minified:
        try:
            size = file_path.stat().st_size
            start = max(0, byte_offset - 500)
            length = min(1000, size - start)

            with open(file_path, "rb") as f:
                f.seek(start)
                raw = f.read(length)
                text = raw.decode(encoding, errors="replace")

                # Simple pretty print by splitting tags and braces
                text_fmt = text.replace("><", ">\n<").replace("},{", "},\n{").replace("},", "},\n")
                lines = text_fmt.splitlines()

                # Highlight the line containing the error (near the center of the snippet)
                middle_idx = len(lines) // 2
                return [
                    ContextLine(
                        line_number=idx + 1,
                        text=line_val.rstrip("\r\n"),
                        is_error_line=(idx == middle_idx)
                    )
                    for idx, line_val in enumerate(lines)
                ]
        except Exception as exc:
            logger.warning("Failed to extract minified context: %s", exc)
            return []

    # Standard file: line-based extraction
    start = max(1, error_line - context_count)
    end = error_line + context_count

    context: list[ContextLine] = []

    try:
        with open(file_path, "r", encoding=encoding, errors="replace") as fh:
            for line_no, line_text in enumerate(fh, start=1):
                if line_no > end:
                    break
                if line_no >= start:
                    context.append(
                        ContextLine(
                            line_number=line_no,
                            text=line_text.rstrip("\n\r"),
                            is_error_line=(line_no == error_line),
                        )
                    )
    except OSError as exc:
        logger.warning("Failed to extract context from %s: %s", file_path, exc)

    return context


# ─────────────────────────────────────────────────────────────────────────
# Severity mapping
# ─────────────────────────────────────────────────────────────────────────

def _map_severity(level: int) -> ErrorSeverity:
    """Map an lxml error-log level to :class:`ErrorSeverity`.

    lxml levels:  1 = WARNING, 2 = ERROR, 3 = FATAL.
    """
    if level >= 3:
        return ErrorSeverity.FATAL
    if level >= 2:
        return ErrorSeverity.ERROR
    return ErrorSeverity.WARNING


# ─────────────────────────────────────────────────────────────────────────
# Streaming parser
# ─────────────────────────────────────────────────────────────────────────

class StreamingXMLParser:
    """Memory-efficient, incremental XML parser.

    Uses lxml's ``XMLParser`` in *recover* mode, feeding the file in
    fixed-size chunks.  After the full file has been consumed the
    parser's error log is inspected to produce structured
    :class:`ValidationError` objects.

    Args:
        context_line_count: How many lines of context to extract
                            around each error.
    """

    def __init__(self, context_line_count: int = 10) -> None:
        self._context_count = context_line_count

    def parse(
        self,
        file_path: Path,
        encoding: str = "utf-8",
        progress_callback: Callable[[int, int], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> tuple[list[ValidationError], FileInfo]:
        """Parse *file_path* incrementally and collect validation errors.

        Args:
            file_path:         Path to the XML file.
            encoding:          Detected encoding of the file.
            progress_callback: ``callback(bytes_read, total_bytes)`` —
                               invoked after every chunk.
            cancel_event:      Set this event to abort parsing early.

        Returns:
            A 2-tuple of ``(errors, file_info)`` where *errors* is a
            list of :class:`ValidationError` and *file_info* captures
            metadata about the parsed file.
        """
        logger.info("Starting streaming parse of %s", file_path.name)

        total_size = file_path.stat().st_size
        file_info = FileInfo(
            filename=file_path.name,
            absolute_path=str(file_path.resolve()),
            file_size=total_size,
            encoding=encoding,
        )

        errors: list[ValidationError] = []
        error_log = []

        try:
            with open(file_path, "rb") as raw_f:
                wrapper = ProgressFileWrapper(raw_f, total_size, progress_callback)
                context = etree.iterparse(
                    wrapper,
                    events=('end',),
                    recover=True,
                    huge_tree=True,
                    resolve_entities=False,
                    no_network=True
                )

                for event, elem in context:
                    if cancel_event is not None and cancel_event.is_set():
                        logger.info("Parse cancelled by user")
                        break

                    # Capture root element metadata
                    if not file_info.root_element:
                        root = elem.getroottree().getroot()
                        if root is not None:
                            tag = root.tag
                            if isinstance(tag, str):
                                if tag.startswith("{"):
                                    file_info.root_element = tag.split("}", 1)[1]
                                else:
                                    file_info.root_element = tag
                            nsmap = root.nsmap if hasattr(root, "nsmap") else {}
                            file_info.namespace_count = len(nsmap)

                    elem.clear()
                    parent = elem.getparent()
                    if parent is not None:
                        while elem.getprevious() is not None:
                            del parent[0]

                error_log = context.error_log

        except etree.XMLSyntaxError as exc:
            error_log = getattr(exc, "error_log", None)
            if not error_log:
                line, col = getattr(exc, "position", (1, 1))
                errors.append(
                    ValidationError(
                        error_number=1,
                        line=line,
                        column=col,
                        byte_offset=self._estimate_byte_offset(line, total_size, self._count_lines(file_path)),
                        message=getattr(exc, "msg", str(exc)),
                        category=categorize_error(getattr(exc, "msg", str(exc))),
                        severity=ErrorSeverity.FATAL,
                        context_lines=extract_context_lines(file_path, line, self._context_count, encoding)
                    )
                )
                error_log = []
        except OSError as exc:
            logger.error("IO error while reading %s: %s", file_path, exc)
            errors.append(
                ValidationError(
                    error_number=1,
                    line=1,
                    column=1,
                    byte_offset=0,
                    message=str(exc),
                    category=ErrorCategory.OTHER,
                    severity=ErrorSeverity.FATAL,
                )
            )
            return errors, file_info

        # Extract XML version from file head.
        file_info.xml_version = self._extract_xml_version(file_path)

        # Count total lines.
        file_info.line_count = self._count_lines(file_path)

        idx = len(errors) + 1
        for entry in error_log:
            line = entry.line if entry.line else 1
            column = entry.column if entry.column else 1
            message = entry.message or "Unknown error"
            byte_offset = self._estimate_byte_offset(line, total_size, file_info.line_count or 1)
            category = categorize_error(message)
            severity = _map_severity(entry.level)
            context = extract_context_lines(
                file_path, line, self._context_count, encoding, byte_offset=byte_offset
            )
            tag_name, reference_tag, reference_line = extract_tag_info(message, category)

            errors.append(
                ValidationError(
                    error_number=idx,
                    line=line,
                    column=column,
                    byte_offset=byte_offset,
                    message=message,
                    category=category,
                    severity=severity,
                    context_lines=context,
                    tag_name=tag_name,
                    reference_tag=reference_tag,
                    reference_line=reference_line,
                )
            )
            idx += 1

        if total_size == 0 and not errors:
            errors.append(
                ValidationError(
                    error_number=1,
                    line=1,
                    column=1,
                    byte_offset=0,
                    message="Document is empty",
                    category=ErrorCategory.UNEXPECTED_EOF,
                    severity=ErrorSeverity.FATAL,
                )
            )

        # --- Suppress cascading ancestor tag mismatch errors ---
        filtered_errors = []
        last_root_mismatch = None # (open_line, close_line)
        
        for err in errors:
            if err.category.value == "Tag Mismatch":
                close_line = err.line
                open_line = err.reference_line
                
                if last_root_mismatch is not None:
                    root_open, root_close = last_root_mismatch
                    # If this mismatch is an ancestor element of the previous mismatched tag
                    # (it opened before it and closed after it), it is a cascade.
                    if open_line < root_open and close_line >= root_close:
                        continue # Suppress
                
                # New root cause tag mismatch
                last_root_mismatch = (open_line, close_line)
            else:
                # Keep active root mismatch context across non-mismatch errors
                pass
            filtered_errors.append(err)
            
        # Re-index remaining errors
        for i, err in enumerate(filtered_errors, start=1):
            err.error_number = i
            
        errors = filtered_errors

        logger.info(
            "Parse complete — %d error(s) found in %s (%d suppressed as cascades)",
            len(errors),
            file_path.name,
            idx - 1 - len(errors)
        )
        return errors, file_info


    # ── Private helpers ──────────────────────────────────────────────────

    @staticmethod
    def _extract_xml_version(file_path: Path) -> str:
        """Read the ``version`` attribute from the XML declaration."""
        import re

        try:
            with open(file_path, "rb") as fh:
                head = fh.read(256)
            match = re.search(rb'version\s*=\s*["\']([^"\']+)["\']', head)
            if match:
                return match.group(1).decode("ascii", errors="replace")
        except OSError:
            pass
        return "1.0"

    @staticmethod
    def _count_lines(file_path: Path) -> int:
        """Return the total line count of the file (fast binary scan)."""
        count = 0
        try:
            with open(file_path, "rb") as fh:
                while True:
                    buf = fh.read(_CHUNK_SIZE)
                    if not buf:
                        break
                    count += buf.count(b"\n")
        except OSError:
            pass
        # Files without a trailing newline still have at least one line.
        return max(count, 1)

    @staticmethod
    def _estimate_byte_offset(
        error_line: int, total_size: int, total_lines: int
    ) -> int:
        """Rough byte-offset estimate based on average line length."""
        if total_lines <= 0:
            return 0
        avg_line_bytes = total_size / total_lines
        return int((error_line - 1) * avg_line_bytes)
