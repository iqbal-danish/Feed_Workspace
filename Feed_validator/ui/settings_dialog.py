"""
Settings dialog for XML Validator Pro.

Provides a form-based dialog for editing application settings with
grouped controls, an Apply button, and directory browsing.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from validator.models import AppSettings


class SettingsDialog(QDialog):
    """Modal dialog for editing ``AppSettings``.

    Signals:
        settings_applied: Emitted when the *Apply* button is clicked,
            carrying the current ``AppSettings`` snapshot.
    """

    settings_applied = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self._init_ui()

    # ── UI setup ────────────────────────────────────────────────────
    def _init_ui(self) -> None:
        """Build the form layout with grouped settings."""
        main_layout = QVBoxLayout(self)

        # ── Validation group ────────────────────────────────────────
        validation_group = QGroupBox("Validation")
        validation_form = QFormLayout()

        self._context_lines_spin = QSpinBox()
        self._context_lines_spin.setRange(1, 50)
        self._context_lines_spin.setValue(10)
        self._context_lines_spin.setToolTip(
            "Number of source lines shown around each error."
        )
        validation_form.addRow("Context lines:", self._context_lines_spin)

        validation_group.setLayout(validation_form)
        main_layout.addWidget(validation_group)

        # ── Appearance group ────────────────────────────────────────
        appearance_group = QGroupBox("Appearance")
        appearance_form = QFormLayout()

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["Dark", "Light"])
        self._theme_combo.setToolTip("Application colour theme.")
        appearance_form.addRow("Theme:", self._theme_combo)

        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(8, 24)
        self._font_size_spin.setValue(12)
        self._font_size_spin.setToolTip("Font size for the context viewer.")
        appearance_form.addRow("Font size:", self._font_size_spin)

        appearance_group.setLayout(appearance_form)
        main_layout.addWidget(appearance_group)

        # ── General group ───────────────────────────────────────────
        general_group = QGroupBox("General")
        general_form = QFormLayout()

        self._auto_open_check = QCheckBox()
        self._auto_open_check.setToolTip(
            "Automatically open the most recent file on startup."
        )
        general_form.addRow("Auto-open last file:", self._auto_open_check)

        self._max_recent_spin = QSpinBox()
        self._max_recent_spin.setRange(1, 20)
        self._max_recent_spin.setValue(10)
        self._max_recent_spin.setToolTip("Maximum entries in the Recent Files menu.")
        general_form.addRow("Max recent files:", self._max_recent_spin)

        general_group.setLayout(general_form)
        main_layout.addWidget(general_group)

        # ── Export group ────────────────────────────────────────────
        export_group = QGroupBox("Export")
        export_form = QFormLayout()

        dir_layout = QHBoxLayout()
        self._report_dir_edit = QLineEdit()
        self._report_dir_edit.setPlaceholderText("Default: same directory as XML file")
        self._report_dir_edit.setToolTip("Directory for exported validation reports.")
        dir_layout.addWidget(self._report_dir_edit)

        self._browse_button = QPushButton("Browse…")
        self._browse_button.setFixedWidth(90)
        self._browse_button.clicked.connect(self._browse_directory)
        dir_layout.addWidget(self._browse_button)

        export_form.addRow("Report output directory:", dir_layout)
        export_group.setLayout(export_form)
        main_layout.addWidget(export_group)

        # ── button box ──────────────────────────────────────────────
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)

        apply_button = self._button_box.button(QDialogButtonBox.StandardButton.Apply)
        if apply_button is not None:
            apply_button.clicked.connect(self._on_apply)

        main_layout.addWidget(self._button_box)

    # ── public API ──────────────────────────────────────────────────
    def load_settings(self, settings: AppSettings) -> None:
        """Populate the form controls from an ``AppSettings`` instance.

        Args:
            settings: The settings to display.
        """
        self._context_lines_spin.setValue(settings.context_line_count)

        theme_index = self._theme_combo.findText(
            settings.theme.capitalize(),
        )
        if theme_index >= 0:
            self._theme_combo.setCurrentIndex(theme_index)

        self._font_size_spin.setValue(settings.font_size)
        self._auto_open_check.setChecked(settings.auto_open_last_file)
        self._report_dir_edit.setText(settings.report_output_directory)
        self._max_recent_spin.setValue(settings.max_recent_files)

    def get_settings(self) -> AppSettings:
        """Read the current form values into a new ``AppSettings``.

        Returns:
            A freshly constructed ``AppSettings`` reflecting the dialog.
        """
        return AppSettings(
            context_line_count=self._context_lines_spin.value(),
            theme=self._theme_combo.currentText().lower(),
            font_size=self._font_size_spin.value(),
            auto_open_last_file=self._auto_open_check.isChecked(),
            report_output_directory=self._report_dir_edit.text().strip(),
            max_recent_files=self._max_recent_spin.value(),
        )

    # ── slots ───────────────────────────────────────────────────────
    def _browse_directory(self) -> None:
        """Open a native directory picker for the report output path."""
        current = self._report_dir_edit.text().strip()
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Report Output Directory",
            current or "",
        )
        if directory:
            self._report_dir_edit.setText(directory)

    def _on_apply(self) -> None:
        """Emit ``settings_applied`` with the current settings snapshot."""
        self.settings_applied.emit(self.get_settings())
