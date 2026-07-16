"""
Custom status bar for XML Validator Pro.

Displays memory usage (auto-updating), validation speed, and parser
status in three permanent label widgets.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QStatusBar, QWidget

from validator.models import ValidationProgress


def _get_memory_usage_mb() -> float:
    """Return current process memory usage in megabytes.

    Tries ``utils.file_utils.get_memory_usage_mb`` first; falls back to
    ``psutil`` or a zero value if neither is available.
    """
    try:
        from utils.file_utils import get_memory_usage_mb  # type: ignore[import-untyped]
        return get_memory_usage_mb()
    except Exception:
        pass

    try:
        import psutil  # type: ignore[import-untyped]
        proc = psutil.Process()
        return proc.memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


class ValidatorStatusBar(QStatusBar):
    """Status bar with three permanent indicator widgets.

    The indicators (separated visually by ``|``) show:

    * **Memory** — process RSS updated every second via ``QTimer``.
    * **Speed** — validation throughput in MB/s.
    * **Status** — current parser state label.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_widgets()
        self._init_timer()

    # ── setup ───────────────────────────────────────────────────────
    def _init_widgets(self) -> None:
        """Create the three permanent labels."""
        separator_style = "color: #666; padding: 0 6px;"

        self._memory_label = QLabel("Memory: — MB")
        self._memory_label.setObjectName("statusMemory")
        self.addPermanentWidget(self._memory_label)

        sep1 = QLabel("|")
        sep1.setStyleSheet(separator_style)
        self.addPermanentWidget(sep1)

        self._speed_label = QLabel("Speed: — MB/s")
        self._speed_label.setObjectName("statusSpeed")
        self.addPermanentWidget(self._speed_label)

        sep2 = QLabel("|")
        sep2.setStyleSheet(separator_style)
        self.addPermanentWidget(sep2)

        self._status_label = QLabel("Status: Idle")
        self._status_label.setObjectName("statusState")
        self.addPermanentWidget(self._status_label)

    def _init_timer(self) -> None:
        """Start the 1-second memory usage timer."""
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_memory)
        self._timer.start()
        # Kick off an immediate reading
        self._update_memory()

    # ── public API ──────────────────────────────────────────────────
    def update_progress(self, progress: ValidationProgress) -> None:
        """Update the speed display from a ``ValidationProgress`` snapshot.

        Args:
            progress: The latest progress data emitted by the worker.
        """
        speed = progress.processing_speed_mbps
        self._speed_label.setText(f"Speed: {speed:.2f} MB/s")

    def set_status(self, status: str) -> None:
        """Set the parser-status text.

        Args:
            status: A short label such as ``'Idle'``, ``'Validating...'``,
                ``'Complete'``, ``'Cancelled'``, or ``'Error'``.
        """
        self._status_label.setText(f"Status: {status}")

    def reset(self) -> None:
        """Restore all indicators to their default values."""
        self._speed_label.setText("Speed: — MB/s")
        self._status_label.setText("Status: Idle")
        self._update_memory()

    # ── internal ────────────────────────────────────────────────────
    def _update_memory(self) -> None:
        """Refresh the memory usage label."""
        mb = _get_memory_usage_mb()
        self._memory_label.setText(f"Memory: {mb:.1f} MB")
