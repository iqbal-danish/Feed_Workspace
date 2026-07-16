"""Application entry point for the XML feed merger."""

from __future__ import annotations

import argparse
from pathlib import Path

from config import MergerConfig


def start_web_server() -> None:
    """Launch local FastAPI server and open default web browser."""
    import time
    import webbrowser
    import uvicorn
    import threading

    def open_browser():
        time.sleep(1.0)
        webbrowser.open("http://127.0.0.1:8000/")

    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run("core.web_server:app", host="127.0.0.1", port=8000, log_level="info")


async def run_cli(args: argparse.Namespace) -> None:
    """Run the merger without opening the desktop application."""
    from core.logger import configure_logging
    from core.merger import FeedMerger

    config = MergerConfig(
        feeds_file=args.feeds,
        output_file=args.output,
        pretty_print=args.pretty,
    )
    configure_logging(config.logs_dir / "merger.log")

    merger = FeedMerger(config)
    await merger.run(config.feeds_file)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Merge XML job feeds into one XML file.")
    parser.add_argument("--cli", action="store_true", help="Run without opening the desktop application.")
    parser.add_argument(
        "--feeds",
        type=Path,
        default=Path("feeds.txt"),
        help="Text file containing one feed URL or local XML path per line.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output") / "merged.xml",
        help="Merged XML output file.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Reserved for future pretty-print mode. Streaming mode writes compact XML.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    if arguments.cli:
        import asyncio

        asyncio.run(run_cli(arguments))
    else:
        start_web_server()
