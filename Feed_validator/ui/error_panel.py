"""
Error panel for XML Validator Pro.

Contains a high-performance table model backed by a plain Python list
and a composite widget that wraps a ``QTableView`` with summary label
and context-menu support.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QLabel,
    QMenu,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from validator.models import ErrorSeverity, ValidationError

# ── column definitions ──────────────────────────────────────────────
_COLUMNS: list[str] = [
    "#",
    "Severity",
    "Line",
    "Column",
    "Byte Offset",
    "Error Type",
    "Message",
]

# ── severity colours ────────────────────────────────────────────────
_SEVERITY_COLOURS: dict[ErrorSeverity, QColor] = {
    ErrorSeverity.FATAL: QColor("#ff4444"),
    ErrorSeverity.ERROR: QColor("#ff8c00"),
    ErrorSeverity.WARNING: QColor("#ffd700"),
}


class ErrorTableModel(QAbstractTableModel):
    """Custom table model optimised for streaming validation errors.

    Errors are stored in a flat list.  ``add_error`` appends a row and
    notifies the view, while ``clear`` resets the entire model.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._errors: list[ValidationError] = []
        self._sort_column: int = 0
        self._sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder

    # ── public API ──────────────────────────────────────────────────
    def add_error(self, error: ValidationError) -> None:
        """Append a single error and notify attached views."""
        row = len(self._errors)
        self.beginInsertRows(QModelIndex(), row, row)
        self._errors.append(error)
        self.endInsertRows()

    def clear(self) -> None:
        """Remove all errors and reset the model."""
        self.beginResetModel()
        self._errors.clear()
        self.endResetModel()

    def get_error(self, row: int) -> ValidationError | None:
        """Return the ``ValidationError`` at *row*, or ``None``."""
        if 0 <= row < len(self._errors):
            return self._errors[row]
        return None

    @property
    def error_count(self) -> int:
        """Return the current number of errors in the model."""
        return len(self._errors)

    # ── QAbstractTableModel interface ───────────────────────────────
    def rowCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),
    ) -> int:
        """Return number of error rows."""
        return len(self._errors)

    def columnCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),
    ) -> int:
        """Return number of columns."""
        return len(_COLUMNS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Return column / row header labels."""
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal and 0 <= section < len(_COLUMNS):
                return _COLUMNS[section]
        return None

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Return data for *index* and *role*."""
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._errors):
            return None

        error = self._errors[row]

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_value(error, col)

        if role == Qt.ItemDataRole.ForegroundRole:
            colour = _SEVERITY_COLOURS.get(error.severity)
            if colour is not None:
                return QBrush(colour)

        if role == Qt.ItemDataRole.ToolTipRole and col == 6:
            return error.message

        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """Sort the model by *column*."""
        self._sort_column = column
        self._sort_order = order
        reverse = order == Qt.SortOrder.DescendingOrder

        key_funcs: dict[int, Any] = {
            0: lambda e: e.error_number,
            1: lambda e: e.severity.value,
            2: lambda e: e.line,
            3: lambda e: e.column,
            4: lambda e: e.byte_offset,
            5: lambda e: e.category.value,
            6: lambda e: e.message.lower(),
        }

        key = key_funcs.get(column, lambda e: e.error_number)
        self.beginResetModel()
        self._errors.sort(key=key, reverse=reverse)
        self.endResetModel()

    # ── helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _display_value(error: ValidationError, col: int) -> str:
        """Return the display string for a given column."""
        if col == 0:
            return str(error.error_number)
        if col == 1:
            return error.severity.value
        if col == 2:
            return f"{error.line:,}"
        if col == 3:
            return str(error.column)
        if col == 4:
            return f"{error.byte_offset:,}"
        if col == 5:
            return error.category.value
        if col == 6:
            return error.message
        return ""


class ErrorPanel(QWidget):
    """Composite panel containing a summary label and sortable error table.

    Signals:
        error_selected: Emitted when the user clicks (or keyboard-navigates
            to) a row.  Carries the corresponding ``ValidationError``.
    """

    error_selected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()

    # ── UI setup ────────────────────────────────────────────────────
    def _init_ui(self) -> None:
        """Build child widgets and layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # summary label
        self._summary_label = QLabel("No errors")
        self._summary_label.setObjectName("errorSummaryLabel")
        self._summary_label.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(self._summary_label)

        # model
        self._model = ErrorTableModel(self)

        # table view
        self._table = QTableView(self)
        self._table.setModel(self._model)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setSortingEnabled(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setWordWrap(False)
        self._table.verticalHeader().setVisible(False)

        # header
        header = self._table.horizontalHeader()
        assert header is not None
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self._table)

        # ── connections ─────────────────────────────────────────────
        self._table.customContextMenuRequested.connect(self._show_context_menu)

        # Selection changes → emit error_selected
        selection_model = self._table.selectionModel()
        if selection_model is not None:
            selection_model.currentRowChanged.connect(self._on_current_row_changed)

    # ── public API ──────────────────────────────────────────────────
    def add_error(self, error: ValidationError) -> None:
        """Append an error row and update the summary label."""
        self._model.add_error(error)
        count = self._model.error_count
        self._summary_label.setText(f"{count:,} error{'s' if count != 1 else ''} found")

    def clear(self) -> None:
        """Reset the table and summary."""
        self._model.clear()
        self._summary_label.setText("No errors")

    def auto_resize_columns(self) -> None:
        """Resize columns to their contents (call after batch load)."""
        self._table.resizeColumnsToContents()

    # ── slots ───────────────────────────────────────────────────────
    def _on_current_row_changed(
        self,
        current: QModelIndex,
        _previous: QModelIndex,
    ) -> None:
        """Emit ``error_selected`` for the newly focused row."""
        if current.isValid():
            error = self._model.get_error(current.row())
            if error is not None:
                self.error_selected.emit(error)

    def _show_context_menu(self, pos: Any) -> None:
        """Show right-click context menu at *pos*."""
        menu = QMenu(self)

        action_copy_row = QAction("Copy Row", self)
        action_copy_row.triggered.connect(self._copy_current_row)
        menu.addAction(action_copy_row)

        action_copy_all = QAction("Copy All Errors", self)
        action_copy_all.triggered.connect(self._copy_all_errors)
        menu.addAction(action_copy_all)

        menu.exec(self._table.viewport().mapToGlobal(pos))

    # ── clipboard helpers ───────────────────────────────────────────
    def _copy_current_row(self) -> None:
        """Copy the selected row as tab-separated text."""
        index = self._table.currentIndex()
        if not index.isValid():
            return
        error = self._model.get_error(index.row())
        if error is None:
            return
        text = self._error_to_text(error)
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

    def _copy_all_errors(self) -> None:
        """Copy every error row as tab-separated text."""
        lines: list[str] = []
        for row in range(self._model.error_count):
            error = self._model.get_error(row)
            if error is not None:
                lines.append(self._error_to_text(error))
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText("\n".join(lines))

    @staticmethod
    def _error_to_text(error: ValidationError) -> str:
        """Format a ``ValidationError`` as a single tab-separated line."""
        return (
            f"{error.error_number}\t"
            f"{error.severity.value}\t"
            f"{error.line}\t"
            f"{error.column}\t"
            f"{error.byte_offset:,}\t"
            f"{error.category.value}\t"
            f"{error.message}"
        )
