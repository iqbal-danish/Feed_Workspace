"""
File and system utility functions for XML Validator Pro.

Provides human-readable formatting helpers, OS integration,
and lightweight resource monitoring without external dependencies.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("xml_validator_pro.file_utils")


# ── Size / speed / duration formatting ────────────────────────────────────

def format_file_size(size_bytes: int) -> str:
    """Convert a byte count to a human-readable string.

    Uses binary units (KB = 1 024 bytes) and rounds to two decimals.

    Examples:
        >>> format_file_size(0)
        '0 B'
        >>> format_file_size(1536)
        '1.50 KB'
        >>> format_file_size(2_621_440)
        '2.50 MB'
    """
    if size_bytes < 0:
        return "0 B"

    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size_bytes)

    for unit in units[:-1]:
        if abs(value) < 1024.0:
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0

    return f"{value:.2f} {units[-1]}"


def format_duration(seconds: float) -> str:
    """Convert elapsed seconds to a compact human-readable string.

    Returns formats such as ``'0s'``, ``'42s'``, ``'2m 34s'``,
    or ``'1h 2m 34s'`` depending on magnitude.
    """
    if seconds < 0:
        seconds = 0.0

    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)

    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    # For sub-second durations show one decimal
    if seconds < 1.0:
        return f"{seconds:.1f}s"
    return f"{s}s"


def format_speed(mbps: float) -> str:
    """Convert megabytes-per-second to a string with two decimals.

    Example:
        >>> format_speed(10.0)
        '10.00 MB/s'
    """
    if mbps <= 0:
        return "0.00 MB/s"
    return f"{mbps:.2f} MB/s"



# ── OS integration ───────────────────────────────────────────────────────

def open_containing_folder(path: Path) -> None:
    """Open the OS file explorer to the folder containing *path*.

    Works on Windows, macOS, and Linux.  Errors are logged but
    never propagated so the caller is never interrupted.
    """
    folder = path.parent if path.is_file() else path

    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
        logger.debug("Opened folder: %s", folder)
    except OSError as exc:
        logger.error("Failed to open folder %s: %s", folder, exc)


# ── File metadata ────────────────────────────────────────────────────────

def get_file_modification_time(path: Path) -> str:
    """Return the last-modified timestamp as a human-readable string.

    Format: ``YYYY-MM-DD HH:MM:SS``.  Returns ``'Unknown'`` if the
    file cannot be accessed.
    """
    try:
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError as exc:
        logger.warning("Cannot read modification time for %s: %s", path, exc)
        return "Unknown"


# ── Resource monitoring ──────────────────────────────────────────────────

def get_memory_usage_mb() -> float:
    """Return the current process RSS memory usage in megabytes.

    Uses platform-native APIs via the ``os`` / ``ctypes`` modules to
    avoid a hard dependency on *psutil*.

    Returns ``0.0`` when memory information cannot be determined.
    """
    system = platform.system()

    try:
        if system == "Windows":
            # Use Win32 API via ctypes — no third-party packages needed.
            import ctypes
            import ctypes.wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.wintypes.DWORD),
                    ("PageFaultCount", ctypes.wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            psapi = ctypes.windll.psapi  # type: ignore[attr-defined]
            
            psapi.GetProcessMemoryInfo.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_void_p, ctypes.wintypes.DWORD]
            psapi.GetProcessMemoryInfo.restype = ctypes.wintypes.BOOL
            
            handle = kernel32.GetCurrentProcess()
            if psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            ):
                return counters.WorkingSetSize / (1024.0 * 1024.0)

        else:
            # Linux / macOS — read /proc/self/status or use resource module.
            try:
                with open("/proc/self/status", "r") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            # Value is in kB
                            kb = int(line.split()[1])
                            return kb / 1024.0
            except FileNotFoundError:
                import resource
                # macOS reports in bytes; Linux in KB
                usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                if platform.system() == "Darwin":
                    return usage / (1024.0 * 1024.0)
                return usage / 1024.0

    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not determine memory usage: %s", exc)

    return 0.0

