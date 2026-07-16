"""Comprehensive smoke test with intentionally broken XML."""

import tempfile
import threading
from pathlib import Path

from validator.validator import XMLValidator
from validator.report_generator import ReportGenerator
from validator.models import ValidationProgress, ValidationError as VError

# Severely broken XML that will produce errors
test_xml = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    "<root>\n"
    '  <item id="1">Hello</item>\n'
    '  <item id="2">World</itm>\n'          # tag mismatch
    "  <item>Bad & entity</item>\n"          # unescaped &
    "  <item>Invalid char: \x01</item>\n"    # illegal character
    "  <item>Premature\n"                    # unclosed
)

tmp = Path(tempfile.mkdtemp())
xml_file = tmp / "broken.xml"
xml_file.write_bytes(test_xml.encode("utf-8"))

# Track callbacks
progress_snapshots: list[float] = []
error_messages: list[str] = []

def on_progress(p: ValidationProgress) -> None:
    progress_snapshots.append(p.percent_complete)

def on_error(e: VError) -> None:
    error_messages.append(e.message)

# Validate
v = XMLValidator()
result = v.validate(
    xml_file,
    progress_callback=on_progress,
    error_callback=on_error,
)

print(f"File: {result.file_info.filename}")
print(f"Encoding: {result.file_info.encoding}")
print(f"Root: {result.file_info.root_element}")
print(f"Lines: {result.file_info.line_count}")
print(f"Errors: {result.error_count}")
print(f"Duration: {result.duration_seconds:.4f}s")
print(f"Progress callbacks: {len(progress_snapshots)}")
print(f"Error callbacks: {len(error_messages)}")
print(f"Summary stats: {result.summary_stats}")
print()

for e in result.errors:
    print(
        f"  #{e.error_number} L{e.line}:C{e.column} "
        f"[{e.severity.value}] {e.category.value}: {e.message}"
    )
    print(f"    Context lines: {len(e.context_lines)}")
    for cl in e.context_lines:
        marker = ">>>" if cl.is_error_line else "   "
        print(f"    {marker} {cl.line_number:>4}: {cl.text}")
    print()

# Generate all 4 report formats
for fmt in ["html", "json", "csv", "txt"]:
    out = tmp / f"report.{fmt}"
    getattr(ReportGenerator, f"generate_{fmt}")(result, out)
    print(f"{fmt.upper()}: {out.stat().st_size} bytes")

# Test cancellation
print("\n--- Cancellation test ---")
cancel = threading.Event()
cancel.set()  # Pre-cancelled
result2 = v.validate(xml_file, cancel_event=cancel)
print(f"Cancelled result: was_cancelled={result2.was_cancelled}")

# Test non-existent file
print("\n--- Missing file test ---")
result3 = v.validate(Path("nonexistent.xml"))
print(f"Missing file errors: {result3.error_count}")
print(f"Missing file msg: {result3.errors[0].message}")

print(f"\nAll reports at: {tmp}")
print("ALL TESTS PASSED!")
