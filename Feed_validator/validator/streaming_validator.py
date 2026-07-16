"""
High-level streaming validation orchestrator for XML and JSON.

Supports local files and URL downloads, auto-detects XML vs JSON, and
manages validation progress and cancellation callbacks.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from utils.file_utils import format_file_size, format_speed, get_file_modification_time
from validator.encoding import EncodingDetector
from validator.json_validator import StreamingJSONParser
from validator.models import (
    FileInfo,
    ValidationError,
    ValidationProgress,
    ValidationResult,
)
from validator.parser import StreamingXMLParser

logger = logging.getLogger("xml_validator_pro.streaming_validator")


class StreamingValidator:
    """Validate an XML or JSON file with streaming progress and error callbacks.

    Coordinates downloading, encoding detection, parser selection,
    and progress notifications.
    """

    def __init__(self, context_line_count: int = 10) -> None:
        self._context_count = context_line_count

    def _detect_file_type(self, file_path: Path) -> str:
        """Auto-detect if a file is XML or JSON."""
        suffix = file_path.suffix.lower()
        if suffix == ".json":
            return "json"
        if suffix in (".xml", ".xsd", ".xsl", ".xslt", ".svg", ".xhtml"):
            return "xml"

        # Content peek check
        try:
            with open(file_path, "rb") as f:
                peek = f.read(4096).strip()
                if peek.startswith(b"\xef\xbb\xbf"):
                    peek = peek[3:].strip()
                if peek.startswith((b"{", b"[")):
                    return "json"
        except Exception:
            pass
        return "xml"

    def _download_url(
        self,
        url_str: str,
        temp_file: Path,
        progress_callback: Callable[[ValidationProgress], None] | None,
        cancel_event: threading.Event | None,
    ) -> bool:
        """Download URL streamingly and write to temp_file.

        Returns True on success, False if cancelled or failed.
        """
        logger.info("Downloading URL: %s", url_str)
        start_time = time.perf_counter()

        try:
            req = urllib.request.Request(
                url_str, headers={"User-Agent": "XML-Validator-Pro/1.0"}
            )
            with urllib.request.urlopen(req) as response:
                content_length = response.getheader("Content-Length")
                total_size = int(content_length) if content_length else 0

                bytes_downloaded = 0
                with open(temp_file, "wb") as out_f:
                    while True:
                        if cancel_event is not None and cancel_event.is_set():
                            logger.info("Download cancelled by user")
                            return False

                        chunk = response.read(65536)
                        if not chunk:
                            break

                        out_f.write(chunk)
                        bytes_downloaded += len(chunk)

                        # Emit download progress callback (errors_found = -1 as sentinel)
                        if progress_callback is not None:
                            elapsed = time.perf_counter() - start_time
                            speed = bytes_downloaded / elapsed if elapsed > 0 else 0.0
                            progress_callback(
                                ValidationProgress(
                                    bytes_processed=bytes_downloaded,
                                    total_bytes=total_size or bytes_downloaded,
                                    percent_complete=(
                                        (bytes_downloaded / total_size * 100.0)
                                        if total_size
                                        else 0.0
                                    ),
                                    elapsed_seconds=elapsed,
                                    estimated_remaining_seconds=(
                                        max(
                                            0.0,
                                            (total_size - bytes_downloaded)
                                            / speed,
                                        )
                                        if speed > 0 and total_size
                                        else 0.0
                                    ),
                                    processing_speed_mbps=speed
                                    / (1024.0 * 1024.0),
                                    errors_found=-1,  # Downloading sentinel
                                )
                            )
            logger.info("Download complete: %d bytes written", bytes_downloaded)
            return True
        except Exception as e:
            logger.error("Download failed: %s", e)
            raise

    def validate(
        self,
        file_path_or_url: Path | str,
        progress_callback: Callable[[ValidationProgress], None] | None = None,
        error_callback: Callable[[ValidationError], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ValidationResult:
        """Run a full validation pass on the file or URL."""
        start_wall = time.perf_counter()
        start_dt = datetime.now()

        path_str = str(file_path_or_url)
        is_url = path_str.startswith(("http://", "https://"))

        temp_file_path: Path | None = None
        target_path: Path

        # ── 1. Handle URL Downloads ──────────────────────────────────────
        if is_url:
            # Create a secure temp file
            fd, temp_path_str = tempfile.mkstemp(suffix=".tmp", prefix="xml_val_")
            os.close(fd)
            temp_file_path = Path(temp_path_str)
            target_path = temp_file_path

            try:
                success = self._download_url(
                    path_str, temp_file_path, progress_callback, cancel_event
                )
                if not success:
                    # Cancelled
                    if temp_file_path.exists():
                        temp_file_path.unlink()
                    res = ValidationResult(
                        file_info=FileInfo(
                            filename=path_str.split("/")[-1] or "url_file",
                            absolute_path=path_str,
                        ),
                        was_cancelled=True,
                        start_time=start_dt,
                        end_time=datetime.now(),
                    )
                    res.compute_summary()
                    return res
            except Exception as e:
                if temp_file_path.exists():
                    temp_file_path.unlink()
                raise RuntimeError(f"Failed to fetch content from URL: {e}") from e
        else:
            target_path = Path(file_path_or_url).resolve()

        # ── 2. Detect type & encoding ────────────────────────────────────
        file_type = self._detect_file_type(target_path)
        logger.info("Detected file type: %s", file_type)

        total_bytes = target_path.stat().st_size
        last_modified = (
            get_file_modification_time(target_path) if not is_url else "N/A"
        )

        detector = EncodingDetector()
        encoding = detector.detect(target_path)

        # ── 3. Parse with corresponding parser ───────────────────────────
        error_count_so_far = 0

        def _raw_progress(bytes_read: int, total: int) -> None:
            nonlocal error_count_so_far
            if progress_callback is None:
                return

            elapsed = time.perf_counter() - start_wall
            percent = (bytes_read / total * 100.0) if total > 0 else 0.0
            speed = bytes_read / elapsed if elapsed > 0 else 0.0

            if percent > 0:
                estimated_total = elapsed / (percent / 100.0)
                remaining = max(0.0, estimated_total - elapsed)
            else:
                remaining = 0.0

            progress = ValidationProgress(
                bytes_processed=bytes_read,
                total_bytes=total,
                current_line=0,
                percent_complete=min(percent, 100.0),
                elapsed_seconds=elapsed,
                estimated_remaining_seconds=remaining,
                processing_speed_mbps=speed / (1024.0 * 1024.0),
                errors_found=error_count_so_far,
            )
            progress_callback(progress)

        if file_type == "json":
            parser = StreamingJSONParser(context_line_count=self._context_count)
        else:
            parser = StreamingXMLParser(context_line_count=self._context_count)

        errors, file_info = parser.parse(
            target_path,
            encoding=encoding,
            progress_callback=_raw_progress,
            cancel_event=cancel_event,
        )

        # Clean up temp file
        if temp_file_path and temp_file_path.exists():
            try:
                temp_file_path.unlink()
            except OSError:
                pass

        # Update metadata details
        if is_url:
            file_info.filename = path_str.split("/")[-1] or "url_file"
            file_info.absolute_path = path_str
            file_info.last_modified = "URL Source"
        else:
            file_info.last_modified = last_modified

        file_info.encoding = encoding

        # ── 4. Fire error callbacks ──────────────────────────────────────
        for err in errors:
            error_count_so_far += 1
            if error_callback is not None:
                try:
                    error_callback(err)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("error_callback raised: %s", exc)

        # ── 5. Build result ──────────────────────────────────────────────
        end_wall = time.perf_counter()
        end_dt = datetime.now()
        duration = end_wall - start_wall

        was_cancelled = cancel_event is not None and cancel_event.is_set()
        file_info.validation_duration = duration

        result = ValidationResult(
            file_info=file_info,
            errors=errors,
            start_time=start_dt,
            end_time=end_dt,
            duration_seconds=duration,
            was_cancelled=was_cancelled,
        )
        result.compute_summary()

        logger.info(
            "Validation complete — %d error(s) in %s",
            len(errors),
            file_info.filename,
        )
        return result


class StreamingXmlValidator:
    """Compatibility wrapper for tests expecting StreamingXmlValidator."""

    def __init__(
        self,
        path: Path,
        progress_callback: Callable[[ValidationProgress], None] | None = None,
        error_callback: Callable[[ValidationError], None] | None = None,
        cancel_event: threading.Event | None = None,
        context_line_count: int = 10,
    ) -> None:
        self.path = Path(path)
        self.progress_callback = progress_callback
        self.error_callback = error_callback
        self.cancel_event = cancel_event
        self.context_line_count = context_line_count

    def validate(self) -> ValidationResult:
        validator = StreamingValidator(context_line_count=self.context_line_count)
        return validator.validate(
            self.path,
            progress_callback=self.progress_callback,
            error_callback=self.error_callback,
            cancel_event=self.cancel_event,
        )
