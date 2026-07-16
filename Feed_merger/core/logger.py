"""Logging setup for the feed merger."""

from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(log_file: Path) -> None:
    """Configure console and file logging."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )
