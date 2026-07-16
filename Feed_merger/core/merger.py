import asyncio
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

from config import MergerConfig
from core.deduplicator import SQLiteDeduplicator
from core.downloader import FeedDownloader
from core.parser import XMLFeedParser
from core.statistics import MergeStatistics
from core.validator import FileValidator
from core.writer import get_stream_writer

logger = logging.getLogger(__name__)


class FeedMerger:
    """Coordinate downloads, parsing, deduplication, writing, and validation."""

    def __init__(self, config: MergerConfig) -> None:
        self.config = config
        self.downloader = FeedDownloader(config)
        self.parser = XMLFeedParser(config)
        self.validator = FileValidator()
        self.statistics = MergeStatistics()

    async def run(self, feeds_file: Path) -> None:
        """Merge all feed sources listed in the feeds configuration file."""
        self._prepare_directories()
        if self.config.reset_duplicate_db:
            self.config.duplicate_db.unlink(missing_ok=True)
            
        sources = self._read_sources(feeds_file)
        self.statistics.total_feeds = len(sources)
        
        for src in sources:
            key = self._feed_key(src)
            self.statistics.feeds[key] = {
                "status": "pending",
                "file_size_bytes": 0,
                "jobs_parsed": 0,
                "jobs_written": 0,
                "elapsed_seconds": 0.0,
            }
            
        logger.info("Starting merge for %s feed source(s)", len(sources))

        # Identify which sources are remote (URLs, Secure APIs, SFTPs)
        remote_sources = [src for src in sources if src.get("type") in ("url", "secure_api", "sftp")]
        download_map: dict[str, Path] = {}
        semaphore = asyncio.Semaphore(self.config.max_concurrent_downloads)

        async def _download_with_sem(src: dict) -> tuple[str, Path | Exception]:
            key = self._feed_key(src)
            self.statistics.feeds[key]["status"] = "downloading"
            async with semaphore:
                try:
                    temp_path = await self.downloader.download(src)
                    return key, temp_path
                except Exception as exc:
                    return key, exc

        if remote_sources:
            logger.info(
                "Downloading %s feed(s) concurrently (max_concurrency=%s)...",
                len(remote_sources),
                self.config.max_concurrent_downloads,
            )
            download_tasks = [_download_with_sem(src) for src in remote_sources]
            results = await asyncio.gather(*download_tasks)
            for key, result in results:
                if isinstance(result, Exception):
                    self.statistics.failed_feeds += 1
                    self.statistics.feeds[key]["status"] = "failed"
                    logger.error("Failed to download feed %s: %s", key, result)
                else:
                    download_map[key] = result
                    try:
                        self.statistics.feeds[key]["file_size_bytes"] = result.stat().st_size
                    except Exception:
                        pass

        with SQLiteDeduplicator(self.config.duplicate_db, self.config.duplicate_fields) as dedupe:
            with get_stream_writer(self.config.output_file, self.config.root_output_node) as writer:
                for src in sources:
                    await self._process_source(src, download_map, dedupe, writer)

        self.validator.validate_file(self.config.output_file)
        self.statistics.write_json(self.config.statistics_file)
        logger.info("Merge complete: %s", self.statistics.snapshot())

    async def _process_source(
        self,
        source_cfg: dict,
        download_map: dict[str, Path],
        dedupe: SQLiteDeduplicator,
        writer: object,
    ) -> None:
        temp_path: Path | None = None
        started_at = time.perf_counter()
        key = self._feed_key(source_cfg)
        self.statistics.feeds[key]["status"] = "processing"
        try:
            src_type = source_cfg.get("type")
            if src_type in ("url", "secure_api", "sftp"):
                if key not in download_map:
                    self.statistics.feeds[key]["status"] = "failed"
                    return
                path = download_map[key]
                temp_path = path
            elif src_type == "file":
                path = Path(source_cfg.get("path", ""))
                if not path.exists():
                    raise FileNotFoundError(f"Feed source does not exist: {path}")
                try:
                    self.statistics.feeds[key]["file_size_bytes"] = path.stat().st_size
                except Exception:
                    pass
            else:
                raise ValueError(f"Unknown source type: {src_type}")

            feed_jobs_parsed = 0
            feed_jobs_written = 0

            for job in self.parser.iter_jobs(path):
                self.statistics.jobs_parsed += 1
                feed_jobs_parsed += 1
                self.statistics.feeds[key]["jobs_parsed"] = feed_jobs_parsed

                if dedupe.seen(job):
                    self.statistics.duplicates_removed += 1
                    continue
                writer.write_element(job)
                self.statistics.jobs_written += 1
                feed_jobs_written += 1
                self.statistics.feeds[key]["jobs_written"] = feed_jobs_written

            self.statistics.successful_feeds += 1
            self.statistics.feeds[key]["status"] = "completed"
            logger.info(
                "Processed %s: parsed=%s written=%s elapsed=%.2fs",
                key,
                feed_jobs_parsed,
                feed_jobs_written,
                time.perf_counter() - started_at,
            )
        except Exception:
            self.statistics.failed_feeds += 1
            self.statistics.feeds[key]["status"] = "failed"
            logger.exception("Failed to process feed source: %s", key)
        finally:
            self.statistics.feeds[key]["elapsed_seconds"] = time.perf_counter() - started_at
            if temp_path and self.config.delete_temp_files:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception as clean_err:
                    logger.warning("Failed to clean up temp file %s: %s", temp_path, clean_err)

    def _read_sources(self, feeds_file: Path) -> list[dict]:
        json_file = feeds_file.with_suffix(".json")
        if json_file.exists():
            try:
                with json_file.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.error("Failed to read feeds.json: %s", exc)

        # Migration path
        sources = []
        if feeds_file.exists():
            try:
                lines = feeds_file.read_text(encoding="utf-8").splitlines()
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("http://") or line.startswith("https://"):
                        sources.append({"type": "url", "url": line})
                    else:
                        sources.append({"type": "file", "path": line})
                        
                with json_file.open("w", encoding="utf-8") as f:
                    json.dump(sources, f, indent=2)
                logger.info("Migrated feeds.txt to feeds.json successfully.")
            except Exception as exc:
                logger.error("Failed to migrate feeds.txt: %s", exc)

        return sources

    def _feed_key(self, src: dict) -> str:
        src_type = src.get("type", "url")
        if src_type in ("url", "secure_api"):
            return src.get("url", "")
        elif src_type == "file":
            return src.get("path", "")
        elif src_type == "sftp":
            return f"sftp://{src.get('host')}{src.get('remote_path')}"
        return "unknown"

    def _prepare_directories(self) -> None:
        for path in (
            self.config.output_file.parent,
            self.config.downloads_dir,
            self.config.logs_dir,
            self.config.temp_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
