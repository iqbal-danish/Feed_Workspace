# XML Feed Merger

A local, streaming-first Python application for merging many XML job feeds into a single valid XML output file.

## Installation

Requires Python 3.12 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

```bash
python app.py
```

This opens the desktop application, where you can add feed URLs or local XML
files, choose the merged output path, follow progress, and review the last run.

For automation without the GUI, add feed URLs or local XML file paths to
`feeds.txt`, one per line, then run:

```bash
python app.py --cli
```

The default output is written to `output/merged.xml`.

## Architecture

- `app.py` starts the desktop application, or the CLI workflow with `--cli`.
- `config.py` contains all runtime settings.
- `core/downloader.py` streams remote feeds to temporary files.
- `core/parser.py` parses XML with `lxml.iterparse()` one job node at a time.
- `core/deduplicator.py` stores duplicate fingerprints in SQLite.
- `core/writer.py` writes jobs immediately to the merged XML file.
- `core/merger.py` coordinates the pipeline.
- `core/statistics.py` tracks counters and runtime metrics.
- `core/validator.py` validates the final XML output.
- `gui/window.py` provides the Tkinter desktop interface.

## Configuration

Edit `config.py` to change output paths, retry count, timeout, job node names, duplicate fields, concurrency, and temp-file cleanup behavior.

## Performance Notes

The merger is designed around streaming IO. It should never load a complete feed or all jobs into memory. XML parsing should use `iterparse()` and each processed node should be cleared immediately.

## Troubleshooting

- Check `logs/merger.log` for download, parsing, validation, and duplicate-detection details.
- Confirm feeds are reachable and listed one per line in `feeds.txt`.
- For very large feeds, keep `pretty_print` disabled for maximum speed.
