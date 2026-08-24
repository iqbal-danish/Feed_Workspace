"""Streaming XML and JSON parser for job feed documents."""

from __future__ import annotations

import gzip
import logging
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import BinaryIO

from lxml import etree

from config import MergerConfig

logger = logging.getLogger(__name__)


class XMLFeedParser:
    """Yield one parsed job element at a time from XML or JSON streams with auto tag detection."""

    def __init__(self, config: MergerConfig) -> None:
        self.config = config

    def iter_jobs(self, path: Path) -> Iterator[etree._Element]:
        """Stream job elements from XML/JSON or gzip-compressed files."""
        is_json = False
        try:
            with self._open(path) as file:
                sample = file.read(500).strip()
                if sample.startswith((b"{", b"[")):
                    is_json = True
        except Exception as exc:
            logger.warning("Failed to determine format of %s from contents: %s", path, exc)
            is_json = path.suffix.lower() in (".json", ".jsonl") or (
                path.suffixes and len(path.suffixes) >= 2 and path.suffixes[-2].lower() == ".json"
            )

        if is_json:
            import ijson

            with self._open(path) as file:
                try:
                    events = ijson.parse(file)
                    stack: list[str] = []
                    current_job: dict[str, str] | None = None
                    key_stack: list[str] = []
                    job_map_start_depth = 0

                    for _, event, value in events:
                        if event == "start_map":
                            stack.append("map")
                            if len(stack) >= 2 and stack[-2] == "array":
                                current_job = {}
                                key_stack = []
                                job_map_start_depth = stack.count("map")
                        elif event == "end_map":
                            if (
                                current_job is not None
                                and len(stack) >= 2
                                and stack[-2] == "array"
                                and stack[-1] == "map"
                            ):
                                job_elem = etree.Element("job")
                                for k, v in current_job.items():
                                    child = etree.SubElement(job_elem, k)
                                    child.text = str(v) if v is not None else ""
                                yield job_elem
                                current_job = None
                            if stack:
                                stack.pop()
                            if key_stack:
                                key_stack.pop()
                        elif event == "start_array":
                            stack.append("array")
                        elif event == "end_array":
                            if stack:
                                stack.pop()
                        elif current_job is not None:
                            if event == "map_key":
                                map_depth = stack.count("map") - job_map_start_depth
                                while len(key_stack) > map_depth:
                                    key_stack.pop()
                                if len(key_stack) == map_depth:
                                    key_stack.append(value)
                                else:
                                    key_stack[map_depth] = value
                            elif event in ("string", "number", "boolean", "null"):
                                if key_stack:
                                    key_name = "_".join(key_stack)
                                    current_job[key_name] = str(value) if value is not None else ""
                except Exception as json_err:
                    logger.warning("Error parsing JSON feed %s: %s", path, json_err)
        else:
            job_names = {name.lower() for name in self.config.job_node_names}
            detected_tag: str | None = None

            # First pass: try standard configured tags
            matched_any = False
            with self._open(path) as file:
                context = etree.iterparse(
                    file,
                    events=("end",),
                    recover=True,
                    huge_tree=True,
                    resolve_entities=False,
                    encoding=None,
                )
                for _, element in context:
                    local_name = self._local_name(element).lower()
                    if local_name in job_names or (detected_tag and local_name == detected_tag):
                        matched_any = True
                        yield element
                        self._release_element(element)
                del context

            # Fallback auto-detection if standard tags yielded 0 items
            if not matched_any:
                detected_tag = self._detect_repeating_tag(path)
                if detected_tag and detected_tag.lower() not in job_names:
                    logger.info("Auto-detected custom repeating job tag '%s' in %s", detected_tag, path.name)
                    with self._open(path) as file:
                        context = etree.iterparse(
                            file,
                            events=("end",),
                            recover=True,
                            huge_tree=True,
                            resolve_entities=False,
                            encoding=None,
                        )
                        for _, element in context:
                            if self._local_name(element).lower() == detected_tag.lower():
                                yield element
                                self._release_element(element)
                        del context

    def _detect_repeating_tag(self, path: Path) -> str | None:
        """Inspect XML to find the most frequent repeating child tag."""
        tag_counts: dict[str, int] = {}
        try:
            with self._open(path) as file:
                context = etree.iterparse(
                    file,
                    events=("end",),
                    recover=True,
                    huge_tree=True,
                    resolve_entities=False,
                )
                for i, (_, element) in enumerate(context):
                    tag = self._local_name(element).lower()
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
                    self._release_element(element)
                    if i > 2000:
                        break
                del context
        except Exception:
            return None

        # Filter out common root containers
        ignore_tags = {"source", "sources", "jobs", "feed", "feeds", "root", "xml", "document", "results", "response", "data"}
        candidates = [(t, c) for t, c in tag_counts.items() if t not in ignore_tags and c > 1]
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][0]
        return None

    def _open(self, path: Path) -> AbstractContextManager[BinaryIO]:
        if self._is_gzip(path):
            return gzip.open(path, "rb")
        return path.open("rb")

    def _is_gzip(self, path: Path) -> bool:
        if path.suffix.lower() == ".gz" or "".join(path.suffixes).lower().endswith(".xml.gz"):
            return True
        try:
            with path.open("rb") as file:
                return file.read(2) == b"\x1f\x8b"
        except Exception:
            return False

    def _local_name(self, element: etree._Element) -> str:
        return etree.QName(element).localname

    def _release_element(self, element: etree._Element) -> None:
        element.clear()
        parent = element.getparent()
        if parent is None:
            return
        while element.getprevious() is not None:
            del parent[0]
