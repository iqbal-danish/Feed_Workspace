"""
Context viewer panel for XML Validator Pro.

Displays the source lines surrounding a validation error, with the
error line visually highlighted using HTML formatting inside a
read-only ``QTextEdit``.
"""

from __future__ import annotations

import html as html_module

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget

from validator.models import ValidationError

_PLACEHOLDER_TEXT = "Select an error to view context"

# ── default styling colours (work well on both dark and light themes) ───
_ERROR_BG = "#5c1a1a"
_ERROR_TEXT = "#ffcccc"
_NORMAL_TEXT = "#d4d4d4"
_LINE_NO_COLOUR = "#858585"


class ContextPanel(QWidget):
    """Read-only viewer that shows source lines around a validation error.

    The error line is highlighted with a distinct background.  Content is
    rendered as HTML inside a ``QTextEdit`` set to read-only mode with a
    monospace font.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._font_size: int = 12
        self._init_ui()

    # ── UI setup ────────────────────────────────────────────────────
    def _init_ui(self) -> None:
        """Build child widgets."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._title_label = QLabel("Context Viewer")
        self._title_label.setObjectName("contextTitle")
        self._title_label.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(self._title_label)

        self._text_edit = QTextEdit(self)
        self._text_edit.setReadOnly(True)
        self._text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._apply_font()
        layout.addWidget(self._text_edit)

        self.clear()

    # ── public API ──────────────────────────────────────────────────
    def show_context(self, error: ValidationError) -> None:
        """Render the context lines for *error*.

        Each line is formatted with its line number.  The error line
        receives a distinct background colour for emphasis.

        Args:
            error: The validation error whose ``context_lines`` to display.
        """
        if not error.context_lines:
            self._text_edit.setHtml(
                f"<p style='color:{_NORMAL_TEXT};'>No context available for "
                f"line {error.line}.</p>"
            )
            return

        # Determine padding width for line numbers
        max_lineno = max(cl.line_number for cl in error.context_lines)
        pad = len(str(max_lineno))

        parts: list[str] = [
            "<pre style='margin:0; padding:6px; font-family:Consolas,\"Courier New\",monospace; "
            f"font-size:{self._font_size}px;'>"
        ]

        for ctx in error.context_lines:
            lineno_str = str(ctx.line_number).rjust(pad)
            escaped_text = html_module.escape(ctx.text.rstrip("\n\r"))

            if ctx.is_error_line:
                parts.append(
                    f"<span style='background-color:{_ERROR_BG}; color:{_ERROR_TEXT}; "
                    f"display:block; padding:1px 4px;'>"
                    f"<span style='color:{_LINE_NO_COLOUR};'>{lineno_str} │ </span>"
                    f"{escaped_text}</span>"
                )
            else:
                parts.append(
                    f"<span style='display:block; padding:1px 4px;'>"
                    f"<span style='color:{_LINE_NO_COLOUR};'>{lineno_str} │ </span>"
                    f"<span style='color:{_NORMAL_TEXT};'>{escaped_text}</span>"
                    f"</span>"
                )

        parts.append("</pre>")
        self._text_edit.setHtml("".join(parts))

        # Update title with error location
        self._title_label.setText(
            f"Context Viewer — Line {error.line}, Column {error.column}"
        )

    def clear(self) -> None:
        """Reset to placeholder text."""
        self._text_edit.setHtml(
            f"<p style='color:#888; font-style:italic; padding:20px; "
            f"font-family:Consolas,\"Courier New\",monospace; "
            f"font-size:{self._font_size}px;'>{_PLACEHOLDER_TEXT}</p>"
        )
        self._title_label.setText("Context Viewer")

    def set_font_size(self, size: int) -> None:
        """Change the monospace font size and refresh.

        Args:
            size: Font point size (clamped to 8–24).
        """
        self._font_size = max(8, min(24, size))
        self._apply_font()
        # Re-render if there's content (caller can call show_context again)
        self.clear()

    # ── helpers ─────────────────────────────────────────────────────
    def _apply_font(self) -> None:
        """Set the monospace font on the text edit."""
        font = QFont("Consolas", self._font_size)
        font.setStyleHint(QFont.StyleHint.Monospace)
        # Fallback
        if not font.exactMatch():
            font = QFont("Courier New", self._font_size)
            font.setStyleHint(QFont.StyleHint.Monospace)
        self._text_edit.setFont(font)
