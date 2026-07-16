"""
Report generation for XML Validator Pro.

Exports validation results in four formats:
- **HTML** — professional dark-themed report with embedded CSS.
- **JSON** — machine-readable via :meth:`ValidationResult.to_json`.
- **CSV**  — spreadsheet-friendly error listing.
- **TXT**  — human-readable plain-text report.
"""

from __future__ import annotations

import csv
import html
import io
import logging
from datetime import datetime
from pathlib import Path

from utils.file_utils import format_duration, format_file_size
from validator.models import ValidationResult

logger = logging.getLogger("xml_validator_pro.report_generator")


class ReportGenerator:
    """Generate validation reports in multiple formats.

    All public methods are **static** — no instance state is needed.
    Every method writes its output to *output_path*, creating parent
    directories if required.
    """

    # ─────────────────────────────────────────────────────────────────────
    # HTML
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_html(result: ValidationResult, output_path: Path) -> None:
        """Write a professional, dark-themed HTML report.

        The report includes file metadata, a summary section, a full
        error table, and context snippets for every error.

        Args:
            result:      The completed validation result.
            output_path: Destination file path.
        """
        logger.info("Generating HTML report → %s", output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        fi = result.file_info
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # ── Inline CSS ───────────────────────────────────────────────────
        css = """\
:root{--bg:#1e1e2e;--surface:#2a2a3c;--border:#3a3a4f;--text:#cdd6f4;
--muted:#a6adc8;--accent:#89b4fa;--error:#f38ba8;--warn:#fab387;
--ok:#a6e3a1;--fatal:#f38ba8;--font:'Segoe UI',Roboto,'Helvetica Neue',sans-serif;
--mono:'Cascadia Code','Fira Code','Consolas',monospace}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--font);
font-size:14px;line-height:1.6;padding:2rem 3rem}
h1{font-size:1.8rem;color:var(--accent);margin-bottom:.25rem}
h2{font-size:1.3rem;color:var(--accent);margin:2rem 0 1rem;
border-bottom:1px solid var(--border);padding-bottom:.4rem}
.subtitle{color:var(--muted);margin-bottom:1.5rem}
table{width:100%;border-collapse:collapse;margin-bottom:1.5rem}
th,td{text-align:left;padding:.55rem .8rem;border:1px solid var(--border)}
th{background:var(--surface);color:var(--accent);font-weight:600}
tr:nth-child(even){background:rgba(42,42,60,.45)}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.8rem;
font-weight:600;text-transform:uppercase}
.badge-error{background:rgba(243,139,168,.18);color:var(--error)}
.badge-warning{background:rgba(250,179,135,.18);color:var(--warn)}
.badge-fatal{background:rgba(243,139,168,.28);color:var(--fatal)}
.badge-ok{background:rgba(166,227,161,.15);color:var(--ok)}
.context{background:var(--surface);border:1px solid var(--border);
border-radius:6px;padding:.6rem .8rem;margin:.5rem 0 1.2rem;
font-family:var(--mono);font-size:.82rem;overflow-x:auto;white-space:pre}
.ctx-err{color:var(--error);font-weight:700}
.ctx-line{color:var(--muted)}
.summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1rem;margin-bottom:1.5rem}
.summary-card{background:var(--surface);border:1px solid var(--border);
border-radius:8px;padding:1rem;text-align:center}
.summary-card .value{font-size:1.8rem;font-weight:700;color:var(--accent)}
.summary-card .label{color:var(--muted);font-size:.85rem}
footer{margin-top:3rem;padding-top:1rem;border-top:1px solid var(--border);
color:var(--muted);font-size:.8rem;text-align:center}
"""

        # ── Helpers ──────────────────────────────────────────────────────
        def _sev_badge(severity_value: str) -> str:
            cls_map = {"Error": "badge-error", "Warning": "badge-warning", "Fatal": "badge-fatal"}
            cls = cls_map.get(severity_value, "badge-error")
            return f'<span class="badge {cls}">{html.escape(severity_value)}</span>'

        def _status_badge() -> str:
            if result.was_cancelled:
                return '<span class="badge badge-warning">CANCELLED</span>'
            if result.has_errors:
                return f'<span class="badge badge-error">{result.error_count} ERROR(S)</span>'
            return '<span class="badge badge-ok">VALID</span>'

        # ── Build HTML ───────────────────────────────────────────────────
        buf = io.StringIO()
        w = buf.write

        w("<!DOCTYPE html>\n<html lang='en'>\n<head>\n")
        w("<meta charset='utf-8'>\n")
        w(f"<title>Validation Report — {html.escape(fi.filename)}</title>\n")
        w(f"<style>{css}</style>\n</head>\n<body>\n")

        # Header
        w(f"<h1>XML Validator Pro — Validation Report</h1>\n")
        w(f'<p class="subtitle">Generated {html.escape(timestamp)}</p>\n')

        # Summary cards
        w('<div class="summary-grid">\n')
        cards = [
            ("Status", _status_badge()),
            ("Errors", str(result.error_count)),
            ("File Size", format_file_size(fi.file_size)),
            ("Duration", format_duration(result.duration_seconds)),
            ("Encoding", html.escape(fi.encoding)),
        ]
        for label, value in cards:
            w(f'<div class="summary-card"><div class="value">{value}</div>')
            w(f'<div class="label">{html.escape(label)}</div></div>\n')
        w("</div>\n")

        # File info
        w("<h2>File Information</h2>\n<table>\n")
        info_rows = [
            ("Filename", fi.filename),
            ("Path", fi.absolute_path),
            ("Size", format_file_size(fi.file_size)),
            ("Encoding", fi.encoding),
            ("XML Version", fi.xml_version),
            ("Root Element", fi.root_element or "—"),
            ("Namespaces", str(fi.namespace_count)),
            ("Lines", str(fi.line_count) if fi.line_count else "—"),
            ("Last Modified", fi.last_modified or "—"),
        ]
        for label, value in info_rows:
            w(f"<tr><th>{html.escape(label)}</th><td>{html.escape(str(value))}</td></tr>\n")
        w("</table>\n")

        # Summary by severity / category
        if result.summary_stats:
            w("<h2>Summary</h2>\n<table>\n")
            w("<tr><th>Metric</th><th>Count</th></tr>\n")
            w(f"<tr><td>Total Errors</td><td>{result.summary_stats.get('total_errors', 0)}</td></tr>\n")
            for sev, cnt in result.summary_stats.get("by_severity", {}).items():
                w(f"<tr><td>Severity: {html.escape(sev)}</td><td>{cnt}</td></tr>\n")
            for cat, cnt in result.summary_stats.get("by_category", {}).items():
                w(f"<tr><td>Category: {html.escape(cat)}</td><td>{cnt}</td></tr>\n")
            w("</table>\n")

        # Error table
        if result.errors:
            w("<h2>Errors</h2>\n<table>\n")
            w("<tr><th>#</th><th>Severity</th><th>Line</th><th>Col</th>")
            w("<th>Byte Offset</th><th>Category</th><th>Message</th></tr>\n")
            for e in result.errors:
                w("<tr>")
                w(f"<td>{e.error_number}</td>")
                w(f"<td>{_sev_badge(e.severity.value)}</td>")
                w(f"<td>{e.line}</td>")
                w(f"<td>{e.column}</td>")
                w(f"<td>{e.byte_offset}</td>")
                w(f"<td>{html.escape(e.category.value)}</td>")
                w(f"<td>{html.escape(e.message)}</td>")
                w("</tr>\n")

                # Context
                if e.context_lines:
                    w('<tr><td colspan="7"><div class="context">')
                    for cl in e.context_lines:
                        cls = "ctx-err" if cl.is_error_line else "ctx-line"
                        prefix = "►" if cl.is_error_line else " "
                        w(f'<span class="{cls}">{prefix} {cl.line_number:>6}: {html.escape(cl.text)}</span>\n')
                    w("</div></td></tr>\n")
            w("</table>\n")
        else:
            w("<h2>Errors</h2>\n<p>No errors found — the document is well-formed.</p>\n")

        # Footer
        w(f'<footer>XML Validator Pro — Report generated {html.escape(timestamp)}</footer>\n')
        w("</body>\n</html>\n")

        output_path.write_text(buf.getvalue(), encoding="utf-8")
        logger.info("HTML report written (%s)", format_file_size(output_path.stat().st_size))

    # ─────────────────────────────────────────────────────────────────────
    # JSON
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_json(result: ValidationResult, output_path: Path) -> None:
        """Write the validation result as a JSON document.

        Args:
            result:      The completed validation result.
            output_path: Destination file path.
        """
        logger.info("Generating JSON report → %s", output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.to_json(indent=2), encoding="utf-8")
        logger.info("JSON report written (%s)", format_file_size(output_path.stat().st_size))

    # ─────────────────────────────────────────────────────────────────────
    # CSV
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_csv(result: ValidationResult, output_path: Path) -> None:
        """Write the error list as a CSV file.

        Columns: ``Error#, Severity, Line, Column, ByteOffset,
        Category, Message``.

        Args:
            result:      The completed validation result.
            output_path: Destination file path.
        """
        logger.info("Generating CSV report → %s", output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                ["Error#", "Severity", "Line", "Column", "ByteOffset", "Category", "Message"]
            )
            for e in result.errors:
                writer.writerow([
                    e.error_number,
                    e.severity.value,
                    e.line,
                    e.column,
                    e.byte_offset,
                    e.category.value,
                    e.message,
                ])

        logger.info("CSV report written (%s)", format_file_size(output_path.stat().st_size))

    # ─────────────────────────────────────────────────────────────────────
    # TXT
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_txt(result: ValidationResult, output_path: Path) -> None:
        """Write a formatted plain-text report.

        Includes file metadata, a summary table, and a detailed
        listing of every error with context snippets.

        Args:
            result:      The completed validation result.
            output_path: Destination file path.
        """
        logger.info("Generating TXT report → %s", output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        fi = result.file_info
        sep = "=" * 72
        thin_sep = "-" * 72
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines: list[str] = []
        a = lines.append

        a(sep)
        a("  XML Validator Pro — Validation Report")
        a(f"  Generated: {timestamp}")
        a(sep)
        a("")

        # File info
        a("FILE INFORMATION")
        a(thin_sep)
        a(f"  Filename       : {fi.filename}")
        a(f"  Path           : {fi.absolute_path}")
        a(f"  Size           : {format_file_size(fi.file_size)}")
        a(f"  Encoding       : {fi.encoding}")
        a(f"  XML Version    : {fi.xml_version}")
        a(f"  Root Element   : {fi.root_element or '—'}")
        a(f"  Namespaces     : {fi.namespace_count}")
        a(f"  Lines          : {fi.line_count if fi.line_count else '—'}")
        a(f"  Last Modified  : {fi.last_modified or '—'}")
        a(f"  Duration       : {format_duration(result.duration_seconds)}")
        a("")

        # Summary
        a("SUMMARY")
        a(thin_sep)
        status = "CANCELLED" if result.was_cancelled else ("ERRORS FOUND" if result.has_errors else "VALID")
        a(f"  Status         : {status}")
        a(f"  Total Errors   : {result.error_count}")
        if result.summary_stats:
            for sev, cnt in result.summary_stats.get("by_severity", {}).items():
                a(f"    {sev:12s}  : {cnt}")
            a("")
            a("  By Category:")
            for cat, cnt in result.summary_stats.get("by_category", {}).items():
                a(f"    {cat:24s}  : {cnt}")
        a("")

        # Errors
        if result.errors:
            a("ERRORS")
            a(sep)
            for e in result.errors:
                a(f"  Error #{e.error_number}")
                a(f"    Severity    : {e.severity.value}")
                a(f"    Line        : {e.line}")
                a(f"    Column      : {e.column}")
                a(f"    Byte Offset : {e.byte_offset}")
                a(f"    Category    : {e.category.value}")
                a(f"    Message     : {e.message}")

                if e.context_lines:
                    a("    Context:")
                    for cl in e.context_lines:
                        marker = ">>>" if cl.is_error_line else "   "
                        a(f"      {marker} {cl.line_number:>6}: {cl.text}")
                a(thin_sep)
        else:
            a("No errors found — the document is well-formed.")
        a("")

        # Footer
        a(sep)
        a(f"  Report generated by XML Validator Pro at {timestamp}")
        a(sep)

        output_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("TXT report written (%s)", format_file_size(output_path.stat().st_size))
