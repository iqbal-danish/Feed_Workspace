import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from config import MergerConfig
from core.logger import configure_logging
from core.merger import FeedMerger

app = FastAPI(title="XML Feed Merger Server")
static_dir = Path(__file__).parent.parent / "web"

# Global queue for Server-Sent Events (SSE) during a merge
sse_queue: asyncio.Queue = asyncio.Queue()
active_merge_thread: threading.Thread | None = None
merge_lock = threading.Lock()


class AsyncQueueHandler(logging.Handler):
    """Custom logging handler to forward logs to an asyncio Queue."""

    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
        super().__init__()
        self.loop = loop
        self.q = queue
        self.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        # Safely enqueue from thread to event loop
        self.loop.call_soon_threadsafe(
            self.q.put_nowait, {"type": "log", "message": msg}
        )


def _worker_merge(config: MergerConfig, loop: asyncio.AbstractEventLoop) -> None:
    """Worker function running in a background thread."""
    configure_logging(config.logs_dir / "merger.log")
    handler = AsyncQueueHandler(loop, sse_queue)
    root = logging.getLogger()
    root.addHandler(handler)

    merger = FeedMerger(config)
    stop_event = threading.Event()

    def stats_publisher() -> None:
        while not stop_event.is_set():
            time.sleep(0.2)
            stats = merger.statistics.snapshot()
            loop.call_soon_threadsafe(
                sse_queue.put_nowait, {"type": "progress", "data": stats}
            )

    pub_thread = threading.Thread(target=stats_publisher, daemon=True)
    pub_thread.start()

    try:
        asyncio.run(merger.run(config.feeds_file))
        stop_event.set()
        pub_thread.join(timeout=1.0)
        # Put final snapshot
        loop.call_soon_threadsafe(
            sse_queue.put_nowait, {"type": "done", "data": merger.statistics.snapshot()}
        )
    except Exception as exc:
        stop_event.set()
        pub_thread.join(timeout=1.0)
        loop.call_soon_threadsafe(
            sse_queue.put_nowait, {"type": "error", "message": str(exc)}
        )
    finally:
        root.removeHandler(handler)


@app.get("/api/config")
def get_config():
    """Retrieve the current app configurations."""
    config = MergerConfig()
    return {
        "feeds_file": str(config.feeds_file),
        "output_file": str(config.output_file),
        "delete_temp_files": config.delete_temp_files,
        "reset_duplicate_db": config.reset_duplicate_db,
    }


@app.get("/api/feeds")
def get_feeds():
    """Load feeds from feeds.json (with feeds.txt migration)."""
    config = MergerConfig()
    from core.merger import FeedMerger
    merger = FeedMerger(config)
    return merger._read_sources(config.feeds_file)


@app.post("/api/feeds")
def save_feeds(feeds: list[dict]):
    """Save the updated feeds list back to feeds.json."""
    config = MergerConfig()
    json_file = config.feeds_file.with_suffix(".json")
    json_file.parent.mkdir(parents=True, exist_ok=True)
    import json
    with json_file.open("w", encoding="utf-8") as f:
        json.dump(feeds, f, indent=2)
    return {"status": "success"}


@app.post("/api/browse/output")
def browse_output():
    """Open a native OS file dialog to choose output XML location."""
    import tkinter as tk
    from tkinter import filedialog
    from gui.window import _enable_windows_dpi_awareness

    root = tk.Tk()
    root.withdraw()
    _enable_windows_dpi_awareness()

    config = MergerConfig()
    selected_path = filedialog.asksaveasfilename(
        title="Save merged XML",
        defaultextension=".xml",
        filetypes=[("XML", "*.xml"), ("All files", "*.*")],
        initialfile=config.output_file.name
    )
    root.destroy()
    return {"path": selected_path or str(config.output_file)}


@app.post("/api/browse/input")
def browse_input():
    """Open a native OS file dialog to select multiple XML feed files."""
    import tkinter as tk
    from tkinter import filedialog
    from gui.window import _enable_windows_dpi_awareness

    root = tk.Tk()
    root.withdraw()
    _enable_windows_dpi_awareness()

    selected_paths = filedialog.askopenfilenames(
        title="Select XML feeds",
        filetypes=[("XML feeds", "*.xml *.gz"), ("All files", "*.*")]
    )
    root.destroy()
    return {"paths": list(selected_paths)}


@app.post("/api/open-output")
def open_output(payload: dict):
    """Open the output XML file locally on the host machine using default application."""
    import os
    from pathlib import Path
    
    file_path_str = payload.get("path", "")
    if not file_path_str:
        return {"status": "error", "message": "No file path specified"}
        
    path = Path(file_path_str)
    if not path.is_absolute():
        path = Path.cwd() / path
        
    if not path.exists():
        return {"status": "error", "message": f"File does not exist: {path.name}"}
        
    try:
        os.startfile(str(path))
        return {"status": "success"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@app.post("/api/merge/start")
async def start_merge(payload: dict):
    """Trigger the merge background thread."""
    global active_merge_thread

    with merge_lock:
        if active_merge_thread and active_merge_thread.is_alive():
            return {"status": "error", "message": "A merge is already running."}

        # Clear existing SSE queue
        while not sse_queue.empty():
            try:
                sse_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        config = MergerConfig(
            feeds_file=Path(payload.get("feeds_file", "feeds.txt")),
            output_file=Path(payload.get("output_file", "output/merged.xml")),
            delete_temp_files=payload.get("delete_temp_files", True),
            reset_duplicate_db=payload.get("reset_duplicate_db", True),
        )

        loop = asyncio.get_running_loop()
        active_merge_thread = threading.Thread(
            target=_worker_merge, args=(config, loop), daemon=True
        )
        active_merge_thread.start()

    return {"status": "success", "message": "Merge started."}


@app.get("/api/merge/events")
async def merge_events(request: Request):
    """SSE Stream sending log messages and stats progress snapshots."""

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            # Check client disconnect
            if await request.is_disconnected():
                break

            try:
                # Wait for next event in the queue
                event = await asyncio.wait_for(sse_queue.get(), timeout=1.0)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                # Heartbeat to keep connection alive
                yield ": keepalive\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/")
def read_index():
    """Serve index.html at root."""
    index_file = static_dir / "index.html"
    if not index_file.exists():
        return HTMLResponse(
            "<h2>Web interface assets not found. Build/extract frontend files first.</h2>",
            status_code=404
        )
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


# Mount static assets
app.mount("/", StaticFiles(directory=str(static_dir)), name="web")
