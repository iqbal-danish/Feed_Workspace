"""
Wrapper module matching test expectations for validate_xml.
"""
from __future__ import annotations
import threading
from pathlib import Path
from validator.models import ValidationResult
from validator.validator import XMLValidator

def validate_xml(
    file_path: Path,
    progress_callback=None,
    error_callback=None,
    cancel_event: threading.Event | None = None,
) -> ValidationResult:
    """Validate an XML file, raising FileNotFoundError if it doesn't exist."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    validator = XMLValidator()
    return validator.validate(
        path,
        progress_callback=progress_callback,
        error_callback=error_callback,
        cancel_event=cancel_event,
    )
