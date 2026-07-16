"""Runtime statistics for the merger pipeline."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import psutil


@dataclass(slots=True)
class MergeStatistics:
    """Counters and runtime metrics collected during a merge."""

    started_at: float = field(default_factory=time.time)
    total_feeds: int = 0
    successful_feeds: int = 0
    failed_feeds: int = 0
    jobs_parsed: int = 0
    jobs_written: int = 0
    duplicates_removed: int = 0
    feeds: dict[str, dict] = field(default_factory=dict)

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.started_at

    def snapshot(self) -> dict[str, float | int]:
        process = psutil.Process()
        data = asdict(self)
        data["elapsed_seconds"] = self.elapsed_seconds
        data["memory_rss_mb"] = process.memory_info().rss / (1024 * 1024)
        data["cpu_percent"] = process.cpu_percent(interval=None)
        data["jobs_per_second"] = self.jobs_written / max(self.elapsed_seconds, 0.001)
        return data

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.snapshot(), indent=2), encoding="utf-8")
