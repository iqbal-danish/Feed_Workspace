#!/usr/bin/env python3
"""
XML Validator Pro — Desktop Application Entry Point.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from utils.logger import setup_logging


def main() -> None:
    """Initialize application, configure logger, apply default font, and show MainWindow."""
    # ── Initialize logging ──────────────────────────────────────────────────
    setup_logging()

    # ── Initialize Qt Application ──────────────────────────────────────────
    app = QApplication(sys.argv)
    app.setApplicationName("XML Validator Pro")
    app.setOrganizationName("XMLValidatorPro")
    app.setStyle("Fusion")  # Consistent cross-platform look and feel

    # Apply Segoe UI default sans-serif font
    font = QFont("Segoe UI", 10)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)

    # ── Launch Main Window ──────────────────────────────────────────────────
    window = MainWindow()
    window.show()

    # If an XML file path is passed as command-line argument, open it immediately
    if len(sys.argv) > 1:
        arg_path = Path(sys.argv[1])
        if arg_path.exists() and arg_path.suffix.lower() in (
            ".xml",
            ".xsd",
            ".xsl",
            ".xslt",
            ".svg",
            ".xhtml",
        ):
            window.load_file(arg_path)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
