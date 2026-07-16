"""
Logging configuration for XML Validator Pro.

Provides a centralized logging setup with rotating file output
and console output at configurable levels.
"""

from __future__ import annotations

import logging
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path


_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_LOG_FILE_NAME = "xml_validator_pro.log"
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_BACKUP_COUNT = 3
_ROOT_LOGGER_NAME = "xml_validator_pro"

_is_configured = False


def setup_logging(log_dir: Path | None = None) -> logging.Logger:
    """Configure and return the application root logger.

    Sets up two handlers:
    - **Console** handler at INFO level for user-visible messages.
    - **Rotating file** handler at DEBUG level for full diagnostics.

    The function is idempotent — subsequent calls return the existing
    logger without adding duplicate handlers.

    Args:
        log_dir: Directory for the log file.  Falls back to the
                 system temp directory when *None*.

    Returns:
        The ``xml_validator_pro`` root :class:`logging.Logger`.
    """
    global _is_configured

    logger = logging.getLogger(_ROOT_LOGGER_NAME)

    if _is_configured:
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(_LOG_FORMAT)

    # --- Console handler (INFO) -------------------------------------------
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # --- Rotating file handler (DEBUG) ------------------------------------
    if log_dir is None:
        log_dir = Path(tempfile.gettempdir())
    else:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / _LOG_FILE_NAME

    try:
        file_handler = RotatingFileHandler(
            filename=str(log_file),
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.debug("Log file created at %s", log_file)
    except OSError as exc:
        logger.warning("Could not create log file at %s: %s", log_file, exc)

    _is_configured = True
    logger.info("Logging initialised for XML Validator Pro")
    return logger
