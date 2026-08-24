import asyncio
import json
import logging
import time
from pathlib import Path

from config import MergerConfig
from core.deduplicator import SQLiteDeduplicator
from core.downloader import FeedDownloader
from core.parser import XMLFeedParser
from core.statistics import MergeStatistics
from core.validator import FileValidator
from core.writer import get_stream_writer

logger = logging.getLogger(__name__)


class FeedMerger:
    """Coordinate pipelined downloads, parsing, deduplication, writing, and validation."""

    def __init__(self, config: MergerConfig) -> None:
        self.config = config
        self.downloader = FeedDownloader(config)
        self.parser = XMLFeedParser(config)
        self.validator = FileValidator()
        self.statistics = MergeStatistics()

    async def run(self, feeds_file: Path) -> None:
        """Merge all feed sources using a high-throughput producer-consumer streaming pipeline."""
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
                "error": None,
            }

        logger.info("Starting merge pipeline for %s feed source(s) with concurrency=%s", len(sources), self.config.max_concurrent_downloads)

        # Producer-Consumer queue for streaming downloaded feeds directly into parser/writer
        ready_queue: asyncio.Queue[tuple[dict, Path | Exception]] = asyncio.Queue()
        semaphore = asyncio.Semaphore(self.config.max_concurrent_downloads)

        async def _download_worker(src: dict, session) -> None:
            key = self._feed_key(src)
            src_type = src.get("type", "url")
            if src_type in ("url", "secure_api", "sftp"):
                self.statistics.feeds[key]["status"] = "downloading"
                async with semaphore:
                    try:
                        temp_path = await self.downloader.download(src, session=session)
                        try:
                            self.statistics.feeds[key]["file_size_bytes"] = temp_path.stat().st_size
                        except Exception:
                            pass
                        await ready_queue.put((src, temp_path))
                    except Exception as exc:
                        await ready_queue.put((src, exc))
            elif src_type == "file":
                path = Path(src.get("path", ""))
                if not path.exists():
                    await ready_queue.put((src, FileNotFoundError(f"File not found: {path}")))
                else:
                    try:
                        self.statistics.feeds[key]["file_size_bytes"] = path.stat().st_size
                    except Exception:
                        pass
                    await ready_queue.put((src, path))
            else:
                await ready_queue.put((src, ValueError(f"Unknown source type: {src_type}")))

        async def _producer(session) -> None:
            tasks = [asyncio.create_task(_download_worker(src, session)) for src in sources]
            await asyncio.gather(*tasks, return_exceptions=True)

        async with self.downloader as downloader:
            session = await downloader.get_session()
            producer_task = asyncio.create_task(_producer(session))

            with SQLiteDeduplicator(self.config.duplicate_db, self.config.duplicate_fields) as dedupe:
                with get_stream_writer(self.config.output_file, self.config.root_output_node) as writer:
                    for _ in range(len(sources)):
                        src, result = await ready_queue.get()
                        await self._process_feed_result(src, result, dedupe, writer)
                        ready_queue.task_done()

            await producer_task

        self.validator.validate_file(self.config.output_file)
        self.statistics.write_json(self.config.statistics_file)
        logger.info(
            "Merge complete: %s total unique jobs written (%s duplicates filtered)",
            self.statistics.jobs_written,
            self.statistics.duplicates_removed,
        )

    async def _process_feed_result(
        self,
        source_cfg: dict,
        result: Path | Exception,
        dedupe: SQLiteDeduplicator,
        writer: object,
    ) -> None:
        started_at = time.perf_counter()
        key = self._feed_key(source_cfg)
        src_type = source_cfg.get("type", "url")
        temp_path: Path | None = None

        if isinstance(result, Exception):
            self.statistics.failed_feeds += 1
            self.statistics.feeds[key]["status"] = "failed"
            self.statistics.feeds[key]["error"] = str(result)
            self.statistics.feeds[key]["elapsed_seconds"] = time.perf_counter() - started_at
            logger.error("Feed failed (%s): %s", key, result)
            return

        path = result
        if src_type in ("url", "secure_api", "sftp"):
            temp_path = path

        self.statistics.feeds[key]["status"] = "processing"
        feed_jobs_parsed = 0
        feed_jobs_written = 0

        try:
            for job in self.parser.iter_jobs(path):
                self.statistics.jobs_parsed += 1
                feed_jobs_parsed += 1
                self.statistics.feeds[key]["jobs_parsed"] = feed_jobs_parsed

                if dedupe.seen(job):
                    self.statistics.duplicates_removed += 1
                    continue

                if self.config.tag_source_feed:
                    from lxml import etree as _etree
                    src_tag = _etree.SubElement(job, self.config.source_tag_name)
                    src_tag.text = key

                writer.write_element(job)
                self.statistics.jobs_written += 1
                feed_jobs_written += 1
                self.statistics.feeds[key]["jobs_written"] = feed_jobs_written

            self.statistics.successful_feeds += 1
            self.statistics.feeds[key]["status"] = "completed"
            logger.info(
                "Processed %s: parsed=%s, written=%s in %.2fs",
                Path(key).name if "/" in key or "\\" in key else key,
                feed_jobs_parsed,
                feed_jobs_written,
                time.perf_counter() - started_at,
            )
        except Exception as exc:
            self.statistics.failed_feeds += 1
            self.statistics.feeds[key]["status"] = "failed"
            self.statistics.feeds[key]["error"] = str(exc)
            logger.exception("Failed to parse feed source %s: %s", key, exc)
        finally:
            self.statistics.feeds[key]["elapsed_seconds"] = time.perf_counter() - started_at
            if temp_path and self.config.delete_temp_files:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass

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
