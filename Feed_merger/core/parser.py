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
    """Yield one parsed job element at a time from XML or JSON streams."""

    def __init__(self, config: MergerConfig) -> None:
        self.config = config

    def iter_jobs(self, path: Path) -> Iterator[etree._Element]:
        """Stream job elements from XML/JSON or gzip-compressed files."""
        is_json = False
        try:
            with self._open(path) as file:
                # Read first 500 bytes to check if file content starts as JSON (object or array)
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
                # Streaming parse through ijson events to capture flat or nested lists of job elements
                events = ijson.parse(file)
                stack: list[str] = []
                current_job: dict[str, str] | None = None
                key_stack: list[str] = []
                job_map_start_depth = 0
                
                for _, event, value in events:
                    if event == "start_map":
                        stack.append("map")
                        # First level map inside an array indicates a job item
                        if len(stack) >= 2 and stack[-2] == "array":
                            current_job = {}
                            key_stack = []
                            job_map_start_depth = stack.count("map")
                    elif event == "end_map":
                        if current_job is not None and len(stack) >= 2 and stack[-2] == "array" and stack[-1] == "map":
                            # Convert parsed JSON dictionary to etree._Element to maintain compatibility
                            job_elem = etree.Element("job")
                            for k, v in current_job.items():
                                child = etree.SubElement(job_elem, k)
                                child.text = v
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
                            # Manage key stack hierarchy for nested object keys namespacing
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
        else:
            job_names = {name.lower() for name in self.config.job_node_names}
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
                    if self._local_name(element).lower() in job_names:
                        yield element
                        self._release_element(element)
                del context

    def _open(self, path: Path) -> AbstractContextManager[BinaryIO]:
        if self._is_gzip(path):
            return gzip.open(path, "rb")
        return path.open("rb")

    def _is_gzip(self, path: Path) -> bool:
        if path.suffix.lower() == ".gz" or "".join(path.suffixes).lower().endswith(".xml.gz"):
            return True
        with path.open("rb") as file:
            return file.read(2) == b"\x1f\x8b"

    def _local_name(self, element: etree._Element) -> str:
        return etree.QName(element).localname

    def _release_element(self, element: etree._Element) -> None:
        element.clear()
        parent = element.getparent()
        if parent is None:
            return
        while element.getprevious() is not None:
            del parent[0]
