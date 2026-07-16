"""
Streaming JSON parser for XML Validator Pro.

Validates JSON documents of arbitrary size in O(d) memory, where d is
the maximum nesting depth. Implements a streaming token state machine.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from enum import Enum, auto
from pathlib import Path

from validator.models import (
    ErrorCategory,
    ErrorSeverity,
    FileInfo,
    ValidationError,
)
from validator.parser import ProgressFileWrapper, extract_context_lines

logger = logging.getLogger("xml_validator_pro.json_validator")


class ParserState(Enum):
    START = auto()
    OBJECT_START = auto()
    OBJECT_KEY = auto()
    OBJECT_VALUE = auto()
    OBJECT_AFTER_VALUE = auto()
    OBJECT_AFTER_COMMA = auto()
    ARRAY_START = auto()
    ARRAY_AFTER_VALUE = auto()
    ARRAY_AFTER_COMMA = auto()
    END = auto()


class JSONSyntaxError(ValueError):
    """Exception raised for syntax errors during streaming JSON parsing."""

    def __init__(self, message: str, line: int, column: int) -> None:
        super().__init__(f"{message} at line {line}, column {column}")
        self.message = message
        self.line = line
        self.column = column


class StreamingJSONParser:
    """Memory-efficient, streaming JSON parser.

    Processes JSON stream chunk by chunk, tracking brackets, nesting depth,
    and states without loading the full object tree into memory.
    """

    _NUMBER_RE = re.compile(
        r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$"
    )

    def __init__(self, context_line_count: int = 10) -> None:
        self._context_count = context_line_count

    def _is_valid_number(self, s: str) -> bool:
        return bool(self._NUMBER_RE.match(s))

    def parse(
        self,
        file_path: Path,
        encoding: str = "utf-8",
        progress_callback: Callable[[int, int], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> tuple[list[ValidationError], FileInfo]:
        """Parse JSON file incrementally and collect errors."""
        logger.info("Starting streaming JSON parse of %s", file_path.name)

        total_size = file_path.stat().st_size
        file_info = FileInfo(
            filename=file_path.name,
            absolute_path=str(file_path.resolve()),
            file_size=total_size,
            encoding=encoding,
            xml_version="JSON",  # Standard JSON
        )

        errors: list[ValidationError] = []

        # Count total lines early or compute during parsing
        # We can use the binary line scanner from XML parser
        from validator.parser import StreamingXMLParser
        file_info.line_count = StreamingXMLParser._count_lines(file_path)

        line = 1
        col = 1

        in_string = False
        escape = False
        unicode_escape_count = 0

        string_buf: list[str] = []
        token_buf: list[str] = []
        start_line, start_col = 1, 1

        state = ParserState.START
        stack: list[str] = []  # Tracks 'OBJECT' or 'ARRAY'
        key_stack: list[set[str]] = []  # Duplicate key detection

        def handle_literal_or_number(t_buf: list[str], s_line: int, s_col: int):
            t_str = "".join(t_buf)
            if t_str in ("true", "false", "null"):
                return "LITERAL", t_str, s_line, s_col
            elif self._is_valid_number(t_str):
                return "NUMBER", t_str, s_line, s_col
            else:
                raise JSONSyntaxError(
                    f"Invalid token '{t_str}'", s_line, s_col
                )

        def process_token(
            token_type: str, value: str, t_line: int, t_col: int
        ):
            nonlocal state

            # Setup root element info if not set
            if not file_info.root_element:
                if token_type == "LEFT_BRACE":
                    file_info.root_element = "object"
                elif token_type == "LEFT_BRACKET":
                    file_info.root_element = "array"

            match state:
                case ParserState.START:
                    match token_type:
                        case "LEFT_BRACE":
                            stack.append("OBJECT")
                            key_stack.append(set())
                            state = ParserState.OBJECT_START
                        case "LEFT_BRACKET":
                            stack.append("ARRAY")
                            state = ParserState.ARRAY_START
                        case "STRING" | "NUMBER" | "LITERAL":
                            state = ParserState.END
                        case _:
                            raise JSONSyntaxError(
                                f"Unexpected token '{value}' at start of document",
                                t_line,
                                t_col,
                            )

                case ParserState.OBJECT_START:
                    match token_type:
                        case "STRING":
                            if value in key_stack[-1]:
                                raise JSONSyntaxError(
                                    f"Duplicate object key '{value}'",
                                    t_line,
                                    t_col,
                                )
                            key_stack[-1].add(value)
                            state = ParserState.OBJECT_KEY
                        case "RIGHT_BRACE":
                            if not stack or stack[-1] != "OBJECT":
                                raise JSONSyntaxError(
                                    "Unexpected '}'", t_line, t_col
                                )
                            stack.pop()
                            key_stack.pop()

                            if not stack:
                                state = ParserState.END
                            elif stack[-1] == "OBJECT":
                                state = ParserState.OBJECT_AFTER_VALUE
                            else:
                                state = ParserState.ARRAY_AFTER_VALUE
                        case _:
                            raise JSONSyntaxError(
                                f"Expected object key or '}}', got '{value}'",
                                t_line,
                                t_col,
                            )

                case ParserState.OBJECT_KEY:
                    if token_type == "COLON":
                        state = ParserState.OBJECT_VALUE
                    else:
                        raise JSONSyntaxError(
                            f"Expected ':', got '{value}'", t_line, t_col
                        )

                case ParserState.OBJECT_VALUE:
                    match token_type:
                        case "LEFT_BRACE":
                            stack.append("OBJECT")
                            key_stack.append(set())
                            state = ParserState.OBJECT_START
                        case "LEFT_BRACKET":
                            stack.append("ARRAY")
                            state = ParserState.ARRAY_START
                        case "STRING" | "NUMBER" | "LITERAL":
                            state = ParserState.OBJECT_AFTER_VALUE
                        case _:
                            raise JSONSyntaxError(
                                f"Expected value, got '{value}'", t_line, t_col
                            )

                case ParserState.OBJECT_AFTER_VALUE:
                    match token_type:
                        case "COMMA":
                            state = ParserState.OBJECT_AFTER_COMMA
                        case "RIGHT_BRACE":
                            if not stack or stack[-1] != "OBJECT":
                                raise JSONSyntaxError(
                                    "Unexpected '}'", t_line, t_col
                                )
                            stack.pop()
                            key_stack.pop()

                            if not stack:
                                state = ParserState.END
                            elif stack[-1] == "OBJECT":
                                state = ParserState.OBJECT_AFTER_VALUE
                            else:
                                state = ParserState.ARRAY_AFTER_VALUE
                        case _:
                            raise JSONSyntaxError(
                                f"Expected ',' or '}}', got '{value}'",
                                t_line,
                                t_col,
                            )

                case ParserState.OBJECT_AFTER_COMMA:
                    if token_type == "STRING":
                        if value in key_stack[-1]:
                            raise JSONSyntaxError(
                                f"Duplicate object key '{value}'",
                                t_line,
                                t_col,
                            )
                        key_stack[-1].add(value)
                        state = ParserState.OBJECT_KEY
                    elif token_type == "RIGHT_BRACE":
                        raise JSONSyntaxError(
                            "Trailing comma inside object is not allowed",
                            t_line,
                            t_col,
                        )
                    else:
                        raise JSONSyntaxError(
                            f"Expected object key, got '{value}'",
                            t_line,
                            t_col,
                        )

                case ParserState.ARRAY_START:
                    match token_type:
                        case "LEFT_BRACE":
                            stack.append("OBJECT")
                            key_stack.append(set())
                            state = ParserState.OBJECT_START
                        case "LEFT_BRACKET":
                            stack.append("ARRAY")
                            state = ParserState.ARRAY_START
                        case "STRING" | "NUMBER" | "LITERAL":
                            state = ParserState.ARRAY_AFTER_VALUE
                        case "RIGHT_BRACKET":
                            if not stack or stack[-1] != "ARRAY":
                                raise JSONSyntaxError(
                                    "Unexpected ']'", t_line, t_col
                                )
                            stack.pop()

                            if not stack:
                                state = ParserState.END
                            elif stack[-1] == "OBJECT":
                                state = ParserState.OBJECT_AFTER_VALUE
                            else:
                                state = ParserState.ARRAY_AFTER_VALUE
                        case _:
                            raise JSONSyntaxError(
                                f"Expected array element or ']', got '{value}'",
                                t_line,
                                t_col,
                            )

                case ParserState.ARRAY_AFTER_VALUE:
                    match token_type:
                        case "COMMA":
                            state = ParserState.ARRAY_AFTER_COMMA
                        case "RIGHT_BRACKET":
                            if not stack or stack[-1] != "ARRAY":
                                raise JSONSyntaxError(
                                    "Unexpected ']'", t_line, t_col
                                )
                            stack.pop()

                            if not stack:
                                state = ParserState.END
                            elif stack[-1] == "OBJECT":
                                state = ParserState.OBJECT_AFTER_VALUE
                            else:
                                state = ParserState.ARRAY_AFTER_VALUE
                        case _:
                            raise JSONSyntaxError(
                                f"Expected ',' or ']', got '{value}'",
                                t_line,
                                t_col,
                            )

                case ParserState.ARRAY_AFTER_COMMA:
                    match token_type:
                        case "LEFT_BRACE":
                            stack.append("OBJECT")
                            key_stack.append(set())
                            state = ParserState.OBJECT_START
                        case "LEFT_BRACKET":
                            stack.append("ARRAY")
                            state = ParserState.ARRAY_START
                        case "STRING" | "NUMBER" | "LITERAL":
                            state = ParserState.ARRAY_AFTER_VALUE
                        case "RIGHT_BRACKET":
                            raise JSONSyntaxError(
                                "Trailing comma inside array is not allowed",
                                t_line,
                                t_col,
                            )
                        case _:
                            raise JSONSyntaxError(
                                f"Expected array element, got '{value}'",
                                t_line,
                                t_col,
                            )

                case ParserState.END:
                    raise JSONSyntaxError(
                        f"Unexpected token '{value}' after valid JSON document",
                        t_line,
                        t_col,
                    )

        # Start parsing chunk-by-chunk
        try:
            with open(file_path, "r", encoding=encoding, errors="replace") as fh:
                wrapper = ProgressFileWrapper(fh, total_size, progress_callback)

                # Process file character-by-character from the stream
                has_data = False
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        logger.info("JSON Parse cancelled by user")
                        break

                    chunk = wrapper.read(65536)
                    if not chunk:
                        break

                    has_data = True
                    # If file is binary wrapper returns bytes, decode it
                    decoded_chunk = (
                        chunk.decode(encoding, errors="replace")
                        if isinstance(chunk, bytes)
                        else chunk
                    )

                    for char in decoded_chunk:
                        char_line, char_col = line, col

                        if char == "\n":
                            line += 1
                            col = 1
                        else:
                            col += 1

                        if in_string:
                            if unicode_escape_count > 0:
                                if char not in "0123456789abcdefABCDEF":
                                    raise JSONSyntaxError(
                                        f"Invalid hex digit in unicode escape sequence: '{char}'",
                                        char_line,
                                        char_col,
                                    )
                                unicode_escape_count -= 1
                                string_buf.append(char)
                            elif escape:
                                if char not in '"\\/bfnrtu':
                                    raise JSONSyntaxError(
                                        f"Invalid escape character: '\\{char}'",
                                        char_line,
                                        char_col,
                                    )
                                if char == "u":
                                    unicode_escape_count = 4
                                escape = False
                                string_buf.append(char)
                            elif char == "\\":
                                escape = True
                            elif char == '"':
                                in_string = False
                                process_token(
                                    "STRING",
                                    "".join(string_buf),
                                    start_line,
                                    start_col,
                                )
                                string_buf = []
                            else:
                                if ord(char) < 0x20:
                                    raise JSONSyntaxError(
                                        "Control characters must be escaped in string literals",
                                        char_line,
                                        char_col,
                                    )
                                string_buf.append(char)
                            continue

                        if char in " \t\n\r":
                            if token_buf:
                                t_type, t_val, s_l, s_c = (
                                    handle_literal_or_number(
                                        token_buf, start_line, start_col
                                    )
                                )
                                process_token(t_type, t_val, s_l, s_c)
                                token_buf = []
                            continue

                        if char in "{}[]:,":
                            if token_buf:
                                t_type, t_val, s_l, s_c = (
                                    handle_literal_or_number(
                                        token_buf, start_line, start_col
                                    )
                                )
                                process_token(t_type, t_val, s_l, s_c)
                                token_buf = []

                            token_map = {
                                "{": "LEFT_BRACE",
                                "}": "RIGHT_BRACE",
                                "[": "LEFT_BRACKET",
                                "]": "RIGHT_BRACKET",
                                ":": "COLON",
                                ",": "COMMA",
                            }
                            process_token(
                                token_map[char], char, char_line, char_col
                            )
                            continue

                        if char == '"':
                            if token_buf:
                                raise JSONSyntaxError(
                                    "Unexpected '\"' in document",
                                    char_line,
                                    char_col,
                                )
                            in_string = True
                            start_line = char_line
                            start_col = char_col
                            continue

                        if not token_buf:
                            start_line = char_line
                            start_col = char_col

                        if len(token_buf) > 4096:
                            raise JSONSyntaxError(
                                "Token buffer limit exceeded",
                                start_line,
                                start_col,
                            )
                        token_buf.append(char)

                # Post-parse stream check
                if not (cancel_event is not None and cancel_event.is_set()):
                    if in_string:
                        raise JSONSyntaxError(
                            "Unclosed string at end of document",
                            start_line,
                            start_col,
                        )
                    if escape or unicode_escape_count > 0:
                        raise JSONSyntaxError(
                            "Incomplete escape sequence at end of document",
                            line,
                            col,
                        )

                    if token_buf:
                        t_type, t_val, s_l, s_c = handle_literal_or_number(
                            token_buf, start_line, start_col
                        )
                        process_token(t_type, t_val, s_l, s_c)
                        token_buf = []

                    if not has_data or state == ParserState.START:
                        raise JSONSyntaxError(
                            "Empty or whitespace-only JSON document", 1, 1
                        )

                    if stack:
                        unclosed = "{" if stack[-1] == "OBJECT" else "["
                        raise JSONSyntaxError(
                            f"Unclosed structure: missing closing match for '{unclosed}'",
                            line,
                            col,
                        )

                    if state != ParserState.END:
                        raise JSONSyntaxError(
                            "Incomplete JSON document structure", line, col
                        )

        except JSONSyntaxError as exc:
            # Map exception details into a single ValidationError
            offset = StreamingXMLParser._estimate_byte_offset(
                exc.line, total_size, file_info.line_count or 1
            )
            context = extract_context_lines(
                file_path, exc.line, self._context_count, encoding
            )

            # Categorize the error category based on message keywords
            category = ErrorCategory.MALFORMED_XML
            if "bracket" in exc.message.lower() or "brace" in exc.message.lower() or "structure" in exc.message.lower():
                category = ErrorCategory.TAG_MISMATCH  # closest equivalent for json mismatch
            elif "unclosed string" in exc.message.lower():
                category = ErrorCategory.UNEXPECTED_EOF
            elif "comma" in exc.message.lower():
                category = ErrorCategory.INVALID_ATTRIBUTE  # closest equivalent for syntax separator
            elif "duplicate object key" in exc.message.lower():
                category = ErrorCategory.INVALID_ATTRIBUTE

            errors.append(
                ValidationError(
                    error_number=1,
                    line=exc.line,
                    column=exc.column,
                    byte_offset=offset,
                    message=exc.message,
                    category=category,
                    severity=ErrorSeverity.FATAL,
                    context_lines=context,
                )
            )
        except OSError as exc:
            logger.error("IO error while reading JSON %s: %s", file_path, exc)
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

        logger.info(
            "JSON Parse complete — %d error(s) found in %s",
            len(errors),
            file_path.name,
        )
        return errors, file_info
