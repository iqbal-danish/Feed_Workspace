"""General utility functions for the feed merger."""

from __future__ import annotations

from pathlib import Path


def human_size(size_bytes: int) -> str:
    """Return a compact human-readable file size."""
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def file_size(path: Path) -> int:
    """Return file size in bytes, or zero when the file is missing."""
    return path.stat().st_size if path.exists() else 0
