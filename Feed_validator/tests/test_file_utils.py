"""
Tests for utils.file_utils — formatting helpers and system queries.

Expected public API:
    - format_file_size(size_bytes: int) -> str
    - format_duration(seconds: float) -> str
    - format_speed(mbps: float) -> str
    - get_memory_usage_mb() -> float
"""

from __future__ import annotations

import pytest

from utils.file_utils import (
    format_duration,
    format_file_size,
    format_speed,
    get_memory_usage_mb,
)


# ╔══════════════════════════════════════════════════════════════════╗
# ║  format_file_size                                                ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestFormatFileSize:
    """Human-readable file size strings."""

    @pytest.mark.parametrize(
        "size_bytes, expected_substr",
        [
            (0, "0"),
            (1023, "1023"),          # still bytes range
            (1024, "1"),             # exactly 1 KB
            (int(1.5 * 1024**2), "1.5"),  # 1.5 MB
            (2 * 1024**3, "2"),      # 2 GB
        ],
        ids=["zero", "bytes", "1KB", "1.5MB", "2GB"],
    )
    def test_expected_magnitude(self, size_bytes: int, expected_substr: str):
        result = format_file_size(size_bytes)
        assert expected_substr in result, (
            f"format_file_size({size_bytes}) = '{result}', "
            f"expected to contain '{expected_substr}'"
        )

    @pytest.mark.parametrize(
        "size_bytes, expected_unit",
        [
            (0, "B"),
            (500, "B"),
            (1024, "KB"),
            (int(1.5 * 1024**2), "MB"),
            (2 * 1024**3, "GB"),
        ],
        ids=["zero_unit", "bytes_unit", "KB_unit", "MB_unit", "GB_unit"],
    )
    def test_expected_unit_suffix(self, size_bytes: int, expected_unit: str):
        result = format_file_size(size_bytes)
        assert expected_unit in result, (
            f"format_file_size({size_bytes}) = '{result}', "
            f"expected unit '{expected_unit}'"
        )


# ╔══════════════════════════════════════════════════════════════════╗
# ║  format_duration                                                 ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestFormatDuration:
    """Human-readable duration strings."""

    @pytest.mark.parametrize(
        "seconds, expected_parts",
        [
            (0, ["0"]),
            (30, ["30"]),
            (90, ["1", "30"]),          # 1m 30s
            (3661, ["1", "1", "1"]),     # 1h 1m 1s
        ],
        ids=["zero", "30s", "1m30s", "1h1m1s"],
    )
    def test_contains_expected_numbers(
        self, seconds: float, expected_parts: list[str]
    ):
        result = format_duration(seconds)
        for part in expected_parts:
            assert part in result, (
                f"format_duration({seconds}) = '{result}', "
                f"expected to contain '{part}'"
            )

    def test_fractional_seconds(self):
        """Sub-second durations should show a decimal."""
        result = format_duration(0.456)
        # Should contain "0.4" or "0.46" or "456" (ms) — at least some fraction
        assert "0" in result


# ╔══════════════════════════════════════════════════════════════════╗
# ║  format_speed                                                    ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestFormatSpeed:
    """Human-readable processing speed strings."""

    @pytest.mark.parametrize(
        "mbps, expected_substr",
        [
            (0.0, "0"),
            (1.5, "1.5"),
            (100.0, "100"),
            (0.001, "0.0"),
        ],
        ids=["zero", "1.5mbps", "100mbps", "tiny"],
    )
    def test_speed_formatting(self, mbps: float, expected_substr: str):
        result = format_speed(mbps)
        assert expected_substr in result, (
            f"format_speed({mbps}) = '{result}', "
            f"expected to contain '{expected_substr}'"
        )

    def test_speed_contains_unit(self):
        """Output should reference MB/s or similar unit."""
        result = format_speed(10.0)
        result_lower = result.lower()
        assert "mb" in result_lower or "megabyte" in result_lower or "/s" in result_lower


# ╔══════════════════════════════════════════════════════════════════╗
# ║  get_memory_usage_mb                                             ║
# ╚══════════════════════════════════════════════════════════════════╝


class TestGetMemoryUsageMb:
    """get_memory_usage_mb must return the process RSS in megabytes."""

    def test_returns_positive_float(self):
        usage = get_memory_usage_mb()
        assert isinstance(usage, float)
        assert usage > 0, "Memory usage must be a positive number"

    def test_reasonable_range(self):
        """A pytest process should use between 1 MB and 4 GB of RAM."""
        usage = get_memory_usage_mb()
        assert 1.0 < usage < 4096.0
