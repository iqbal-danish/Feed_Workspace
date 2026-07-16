"""
Application toolbar for XML Validator Pro.

Provides quick-access actions for opening files, running validation,
exporting reports, and accessing settings.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import QStyle, QToolBar, QWidget


class ValidatorToolbar(QToolBar):
    """Main toolbar with file / validation / settings actions.

    Signals:
        open_clicked: Emitted when the *Open XML* button is activated.
        validate_clicked: Emitted when the *Validate* button is activated.
        cancel_clicked: Emitted when the *Cancel* button is activated.
        export_clicked: Emitted when the *Export Report* button is activated.
        clear_clicked: Emitted when the *Clear* button is activated.
        settings_clicked: Emitted when the *Settings* button is activated.
    """

    open_clicked = Signal()
    validate_clicked = Signal()
    cancel_clicked = Signal()
    export_clicked = Signal()
    clear_clicked = Signal()
    settings_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Main Toolbar", parent)

        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setIconSize(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon).availableSizes()[0] if False else __import__("PySide6.QtCore", fromlist=["QSize"]).QSize(24, 24))  # noqa: E501 — ugly one-liner replaced below
        self.setMovable(False)

        # Fix icon size properly
        from PySide6.QtCore import QSize
        self.setIconSize(QSize(24, 24))

        style = self.style()
        assert style is not None

        # ── actions ─────────────────────────────────────────────────
        self.action_open = self._make_action(
            icon=style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            text="Open XML",
            shortcut=QKeySequence("Ctrl+O"),
            tooltip="Open an XML file (Ctrl+O)",
            signal=self.open_clicked,
        )

        self.action_validate = self._make_action(
            icon=style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay),
            text="Validate",
            shortcut=QKeySequence("F5"),
            tooltip="Start validation (F5)",
            signal=self.validate_clicked,
        )

        self.action_cancel = self._make_action(
            icon=style.standardIcon(QStyle.StandardPixmap.SP_MediaStop),
            text="Cancel",
            shortcut=QKeySequence("Escape"),
            tooltip="Cancel running validation (Escape)",
            signal=self.cancel_clicked,
        )
        self.action_cancel.setEnabled(False)

        self.addSeparator()

        self.action_export = self._make_action(
            icon=style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
            text="Export Report",
            shortcut=QKeySequence("Ctrl+E"),
            tooltip="Export validation report (Ctrl+E)",
            signal=self.export_clicked,
        )

        self.action_clear = self._make_action(
            icon=style.standardIcon(QStyle.StandardPixmap.SP_DialogResetButton),
            text="Clear",
            shortcut=QKeySequence("Ctrl+Shift+C"),
            tooltip="Clear all results (Ctrl+Shift+C)",
            signal=self.clear_clicked,
        )

        self.addSeparator()

        self.action_settings = self._make_action(
            icon=style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
            text="Settings",
            shortcut=QKeySequence("Ctrl+,"),
            tooltip="Application settings (Ctrl+,)",
            signal=self.settings_clicked,
        )

    # ── public helpers ──────────────────────────────────────────────
    def set_validation_running(self, running: bool) -> None:
        """Toggle action enabled states based on whether validation is active.

        While validation is running the *Cancel* button is enabled and the
        *Open*, *Validate*, *Export*, *Clear* buttons are disabled.
        """
        self.action_open.setEnabled(not running)
        self.action_validate.setEnabled(not running)
        self.action_cancel.setEnabled(running)
        self.action_export.setEnabled(not running)
        self.action_clear.setEnabled(not running)
        # Settings always available
        self.action_settings.setEnabled(True)

    # ── internal ────────────────────────────────────────────────────
    def _make_action(
        self,
        icon: QIcon,
        text: str,
        shortcut: QKeySequence,
        tooltip: str,
        signal: Signal,
    ) -> QAction:
        """Create a ``QAction``, add it to the toolbar, and wire its signal."""
        action = QAction(icon, text, self)
        action.setShortcut(shortcut)
        action.setToolTip(tooltip)
        action.setStatusTip(tooltip)
        action.triggered.connect(signal.emit)
        self.addAction(action)
        return action
