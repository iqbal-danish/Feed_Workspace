"""
Top-level XML validation façade for XML Validator Pro.

Provides a simple, robust entry-point that validates inputs,
delegates to :class:`StreamingValidator`, and wraps all errors
so callers never see unexpected exceptions.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from utils.file_utils import format_duration, format_file_size
from validator.models import (
    AppSettings,
    ErrorCategory,
    ErrorSeverity,
    FileInfo,
    ValidationError,
    ValidationProgress,
    ValidationResult,
)
from validator.streaming_validator import StreamingValidator

logger = logging.getLogger("xml_validator_pro.validator")


class XMLValidator:
    """Public façade for XML validation.

    Validates that the target file exists and is readable, then
    delegates to :class:`StreamingValidator` for the actual work.
    All unexpected exceptions are caught and surfaced as a single
    FATAL :class:`ValidationError` so the caller always receives
    a well-formed :class:`ValidationResult`.

    Args:
        settings: Optional application settings.  When *None*,
                  sensible defaults are used.
    """

    def __init__(self, settings: AppSettings | None = None) -> None:
        self._settings = settings or AppSettings()

    def validate(
        self,
        file_path: Path | str,
        progress_callback: Callable[[ValidationProgress], None] | None = None,
        error_callback: Callable[[ValidationError], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ValidationResult:
        """Validate *file_path* (or URL) and return a :class:`ValidationResult`.

        Args:
            file_path:         Path or URL to the XML file to validate.
            progress_callback: Called with :class:`ValidationProgress`
                               snapshots during parsing.
            error_callback:    Called once per error for live UI updates.
            cancel_event:      Set to request early abort.

        Returns:
            A fully populated :class:`ValidationResult`.
        """
        path_str = str(file_path)
        is_url = path_str.startswith(("http://", "https://"))

        if is_url:
            logger.info("=== Validation requested (URL): %s ===", path_str)
        else:
            file_path = Path(file_path).resolve()
            logger.info(
                "=== Validation requested: %s ===", file_path.name
            )

            # ── Pre-flight checks ────────────────────────────────────────────
            preflight_error = self._preflight(file_path)
            if preflight_error is not None:
                logger.error("Pre-flight check failed: %s", preflight_error)
                return self._error_result(file_path, preflight_error)

            logger.info(
                "File OK — size %s",
                format_file_size(file_path.stat().st_size),
            )

        # ── Delegate to StreamingValidator ───────────────────────────────
        try:
            sv = StreamingValidator(
                context_line_count=self._settings.context_line_count,
            )
            result = sv.validate(
                path_str if is_url else file_path,
                progress_callback=progress_callback,
                error_callback=error_callback,
                cancel_event=cancel_event,
            )

            logger.info(
                "=== Validation finished: %d error(s) in %s ===",
                result.error_count,
                format_duration(result.duration_seconds),
            )
            return result

        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error during validation of %s", file_path)
            return self._error_result(
                file_path,
                f"Unexpected internal error: {exc}",
            )

    # ── Private helpers ──────────────────────────────────────────────────

    @staticmethod
    def _preflight(file_path: Path) -> str | None:
        """Return an error message if the file is not valid, else *None*."""
        if not file_path.exists():
            return f"File does not exist: {file_path}"

        if not file_path.is_file():
            return f"Path is not a regular file: {file_path}"

        try:
            with open(file_path, "rb") as fh:
                fh.read(1)
        except PermissionError:
            return f"Permission denied: {file_path}"
        except OSError as exc:
            return f"Cannot read file: {exc}"

        return None

    @staticmethod
    def _error_result(file_path: Path | str, message: str) -> ValidationResult:
        """Build a minimal :class:`ValidationResult` for a pre-flight failure."""
        now = datetime.now()
        path_str = str(file_path)
        name = path_str.split("/")[-1] if path_str.startswith(("http://", "https://")) else Path(file_path).name
        
        info = FileInfo(
            filename=name or "url_file",
            absolute_path=path_str,
        )
        error = ValidationError(
            error_number=1,
            line=0,
            column=0,
            byte_offset=0,
            message=message,
            category=ErrorCategory.OTHER,
            severity=ErrorSeverity.FATAL,
        )
        result = ValidationResult(
            file_info=info,
            errors=[error],
            start_time=now,
            end_time=now,
            duration_seconds=0.0,
        )
        result.compute_summary()
        return result
