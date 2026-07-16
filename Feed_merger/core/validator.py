"""Validation helpers for generated XML and JSON output."""

from __future__ import annotations

import json
from pathlib import Path

from lxml import etree


class FileValidator:
    """Validate output XML or JSON syntax well-formedness."""

    def validate_file(self, path: Path) -> bool:
        if path.suffix.lower() == ".json":
            try:
                with path.open("r", encoding="utf-8") as file:
                    json.load(file)
                return True
            except json.JSONDecodeError:
                return False
        else:
            parser = etree.XMLParser(recover=False, huge_tree=True)
            try:
                with path.open("rb") as file:
                    etree.parse(file, parser)
                return True
            except etree.XMLSyntaxError:
                return False
