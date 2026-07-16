"""Application configuration for the XML feed merger."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class MergerConfig:
    """Runtime settings shared by the merger components."""

    output_file: Path = Path("output") / "merged.xml"
    downloads_dir: Path = Path("downloads")
    logs_dir: Path = Path("logs")
    temp_dir: Path = Path("downloads") / "tmp"
    duplicate_db: Path = Path("output") / "duplicates.sqlite3"
    statistics_file: Path = Path("output") / "statistics.json"
    feeds_file: Path = Path("feeds.txt")
    root_output_node: str = "source"
    retry_count: int = 3
    timeout_seconds: int = 60
    chunk_size: int = 1024 * 1024
    delete_temp_files: bool = True
    reset_duplicate_db: bool = True
    max_concurrent_downloads: int = 3
    pretty_print: bool = False
    duplicate_fields: tuple[str, ...] = ("id", "guid", "reference", "url", "apply_url")
    job_node_names: tuple[str, ...] = (
        "job",
        "position",
        "item",
        "entry",
        "opening",
        "vacancy",
    )
    local_file_extensions: tuple[str, ...] = (".xml", ".gz", ".xml.gz")
    request_headers: dict[str, str] = field(
        default_factory=lambda: {"User-Agent": "FeedMerger/1.0"}
    )
