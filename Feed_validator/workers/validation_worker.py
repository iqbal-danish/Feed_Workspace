"""
Validation worker for XML Validator Pro.

Uses the QObject + moveToThread pattern (not QThread subclassing) to run
XML validation in a background thread while emitting Qt signals for
real-time UI updates.
"""

from __future__ import annotations

import logging
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from validator.models import (
    FileInfo,
    ValidationError,
    ValidationProgress,
    ValidationResult,
)
from validator.validator import XMLValidator

logger = logging.getLogger(__name__)


class ValidationWorker(QObject):
    """Background worker that performs XML validation and emits Qt signals.

    This worker is designed to be moved to a ``QThread`` via
    ``worker.moveToThread(thread)``.  The caller should connect
    ``thread.started`` to ``worker.run`` and wire up the cleanup
    chain (``validation_complete -> thread.quit``, etc.).

    Signals:
        progress_updated: Emits a ``ValidationProgress`` periodically.
        error_found: Emits each ``ValidationError`` as it is discovered
            so the UI can stream rows into the error table.
        validation_complete: Emits the final ``ValidationResult``.
        validation_failed: Emits an error-message string when the
            validation run itself raises an unrecoverable exception.
        file_info_ready: Emits ``FileInfo`` as soon as it is available,
            before the full validation finishes.
    """

    # ── signals ──────────────────────────────────────────────────────
    progress_updated = Signal(object)
    error_found = Signal(object)
    validation_complete = Signal(object)
    validation_failed = Signal(str)
    file_info_ready = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._file_path: Path | None = None
        self._cancel_event = threading.Event()
        self._context_line_count: int = 10

    # ── public API (called from the GUI thread before starting) ─────
    def set_file(self, file_path: Path, context_line_count: int = 10) -> None:
        """Configure the file to validate and context-line depth.

        Args:
            file_path: Absolute path to the XML file.
            context_line_count: Number of surrounding lines to capture
                around each error for the context viewer.
        """
        self._file_path = file_path
        self._context_line_count = context_line_count
        self._cancel_event.clear()

    def cancel(self) -> None:
        """Request cancellation of the running validation.

        Thread-safe — may be called from any thread.
        """
        self._cancel_event.set()
        logger.info("Validation cancellation requested.")

    # ── slot executed on the worker thread ──────────────────────────
    @Slot()
    def run(self) -> None:
        """Execute the validation.

        This slot should be connected to ``QThread.started``.  It creates
        an ``XMLValidator``, registers callbacks that emit signals, then
        calls ``validate()``.  On success it emits ``validation_complete``;
        on failure it emits ``validation_failed``.
        """
        if self._file_path is None:
            self.validation_failed.emit("No file path configured.")
            return

        try:
            logger.info("Validation started for %s", self._file_path)

            from validator.models import AppSettings, FileInfo
            from validator.encoding import detect_encoding
            from utils.file_utils import get_file_modification_time

            path_str = str(self._file_path)
            is_url = path_str.startswith(("http://", "https://"))

            if is_url:
                name = path_str.split("/")[-1] or "url_file"
                init_info = FileInfo(
                    filename=name,
                    absolute_path=path_str,
                    file_size=0,
                    encoding="Detecting...",
                    last_modified="URL Source",
                )
                self.file_info_ready.emit(init_info)
            else:
                file_path_obj = Path(self._file_path)
                # Emit initial file info to make UI feel responsive
                init_info = FileInfo(
                    filename=file_path_obj.name,
                    absolute_path=str(file_path_obj.resolve()),
                    file_size=file_path_obj.stat().st_size,
                    encoding="Detecting...",
                    last_modified=get_file_modification_time(file_path_obj),
                )
                self.file_info_ready.emit(init_info)

                # Detect encoding
                try:
                    enc = detect_encoding(file_path_obj)
                    init_info.encoding = enc
                    self.file_info_ready.emit(init_info)
                except Exception as enc_err:
                    logger.warning("Failed to detect encoding early: %s", enc_err)
                enc = "utf-8"

            settings = AppSettings(context_line_count=self._context_line_count)
            validator = XMLValidator(settings=settings)

            # ── callbacks ────────────────────────────────────────────
            def on_progress(progress: ValidationProgress) -> None:
                """Forward progress updates to the UI thread."""
                self.progress_updated.emit(progress)

            def on_error(error: ValidationError) -> None:
                """Forward each error to the UI thread for live display."""
                self.error_found.emit(error)

            result: ValidationResult = validator.validate(
                file_path=self._file_path,
                progress_callback=on_progress,
                error_callback=on_error,
                cancel_event=self._cancel_event,
            )

            # Emit final file info containing all parsed metadata
            self.file_info_ready.emit(result.file_info)

            logger.info(
                "Validation finished — %d error(s), cancelled=%s",
                result.error_count,
                result.was_cancelled,
            )
            self.validation_complete.emit(result)

        except Exception as exc:
            tb = traceback.format_exc()
            message = f"{exc}\n\n{tb}"
            logger.exception("Validation failed with an exception.")
            self.validation_failed.emit(message)

