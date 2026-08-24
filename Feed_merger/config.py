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
    timeout_seconds: int = 45
    chunk_size: int = 1024 * 1024
    delete_temp_files: bool = True
    reset_duplicate_db: bool = True
    max_concurrent_downloads: int = 20
    pretty_print: bool = False
    tag_source_feed: bool = False
    source_tag_name: str = "source_feed_url"
    duplicate_fields: tuple[str, ...] = ("id", "guid", "reference", "url", "apply_url", "job_id", "jobid", "req_id")
    job_node_names: tuple[str, ...] = (
        "job",
        "position",
        "item",
        "entry",
        "opening",
        "vacancy",
        "record",
        "posting",
        "opportunity",
        "listing",
        "work",
        "ad",
        "row",
        "element",
    )
    local_file_extensions: tuple[str, ...] = (".xml", ".gz", ".xml.gz", ".json", ".jsonl")
    request_headers: dict[str, str] = field(
        default_factory=lambda: {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/xml,text/xml,application/xhtml+xml,text/html;q=0.9,application/json,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
    )
