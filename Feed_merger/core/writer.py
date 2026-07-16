"""Streaming XML and JSON output writers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import BinaryIO

from lxml import etree


class XMLStreamWriter:
    """Write a valid XML document incrementally."""

    def __init__(self, output_file: Path, root_node: str) -> None:
        self.output_file = output_file
        self.root_node = root_node
        self.file: BinaryIO | None = None
        self.jobs_written = 0

    def __enter__(self) -> XMLStreamWriter:
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.output_file.open("wb")
        self.file.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        self.file.write(f"<{self.root_node}>\n".encode("utf-8"))
        return self

    def __exit__(self, *_: object) -> None:
        if self.file is None:
            return
        self.file.write(f"</{self.root_node}>\n".encode("utf-8"))
        self.file.flush()
        self.file.close()
        self.file = None

    def write_element(self, element: etree._Element) -> None:
        """Serialize and append one XML element."""
        if self.file is None:
            raise RuntimeError("XMLStreamWriter must be opened before writing")
        self.file.write(
            etree.tostring(
                element,
                encoding="UTF-8",
                xml_declaration=False,
                with_tail=False,
            )
        )
        self.file.write(b"\n")
        self.jobs_written += 1


class JSONStreamWriter:
    """Write a valid JSON array document incrementally."""

    def __init__(self, output_file: Path) -> None:
        self.output_file = output_file
        self.file = None
        self.jobs_written = 0
        self.first = True

    def __enter__(self) -> JSONStreamWriter:
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.output_file.open("w", encoding="utf-8")
        self.file.write("[\n")
        return self

    def __exit__(self, *_: object) -> None:
        if self.file is None:
            return
        self.file.write("\n]\n")
        self.file.close()
        self.file = None

    def write_element(self, element: etree._Element) -> None:
        """Serialize and append one job element as a JSON object inside the array."""
        if self.file is None:
            raise RuntimeError("JSONStreamWriter must be opened before writing")
        
        # Convert XML etree._Element back to key-value dictionary for JSON serialization
        job_dict = {}
        for child in element.iterchildren():
            local_name = etree.QName(child).localname
            job_dict[local_name] = "".join(child.itertext()).strip()
            
        if not self.first:
            self.file.write(",\n")
        else:
            self.first = False
            
        indent = "  "
        serialized = json.dumps(job_dict, indent=2)
        indented = indent + serialized.replace("\n", "\n" + indent)
        self.file.write(indented)
        self.jobs_written += 1


def get_stream_writer(output_file: Path, root_node: str):
    """Factory returning the correct streaming writer based on output file extension."""
    if output_file.suffix.lower() == ".json":
        return JSONStreamWriter(output_file)
    return XMLStreamWriter(output_file, root_node)
