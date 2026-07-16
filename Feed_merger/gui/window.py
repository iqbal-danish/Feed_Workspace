"""Desktop interface for XML feed merging."""

from __future__ import annotations

import asyncio
import ctypes
import logging
import queue
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from config import MergerConfig


def _enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


_enable_windows_dpi_awareness()


class QueueHandler(logging.Handler):
    def __init__(self, messages: queue.Queue[str]) -> None:
        super().__init__()
        self.messages = messages
        self.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.put(self.format(record))


class FeedMergerApp(tk.Tk):
    """Responsive desktop control panel for the streaming merge pipeline."""

    def __init__(self, config: MergerConfig | None = None) -> None:
        super().__init__()
        self.base = config or MergerConfig()
        self.source_values: set[str] = set()
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.result_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker_thread: threading.Thread | None = None

        self.title("XML Feed Merger")
        self.geometry("1120x800")
        self.minsize(900, 680)
        self._styles()
        self._build()
        self.after_idle(self._load_sources)
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        families = set(tkfont.families(self))
        self.font_family = next((font for font in ("Aptos", "Segoe UI") if font in families), "Segoe UI")
        self.mono_family = next((font for font in ("Cascadia Mono", "Consolas") if font in families), "Consolas")
        self.colors = {
            "bg": "#090d16",        # Space dark background
            "panel": "#111827",     # Dark Slate Card
            "ink": "#f1f5f9",       # Primary off-white text
            "muted": "#94a3b8",     # Muted slate-400 text
            "line": "#1f2937",      # Border/Separators slate-800
            "nav": "#030712",       # Sidebar deep black
            "nav_soft": "#111827",  # Sidebar container boxes
            "nav_text": "#f8fafc",  # Navigation text
            "nav_muted": "#64748b", # Navigation muted text
            "accent": "#3b82f6",     # Accent Blue (vibrant)
            "accent_hot": "#2563eb", # Accent Hover Blue
            "green": "#10b981",     # Success Emerald
            "surface": "#1f2937",   # Hover surfaces
            "log": "#020617",       # Log console terminal
        }
        self.configure(bg=self.colors["bg"])
        self.option_add("*Font", (self.font_family, 10))
        
        style.configure("Shell.TFrame", background=self.colors["bg"])
        style.configure("Panel.TFrame", background=self.colors["panel"])
        style.configure("TFrame", background=self.colors["bg"])
        style.configure("Panel.TLabel", background=self.colors["panel"], foreground=self.colors["ink"], font=(self.font_family, 10))
        style.configure("Muted.TLabel", background=self.colors["panel"], foreground=self.colors["muted"], font=(self.font_family, 9))
        
        style.configure("Accent.TButton", padding=(20, 12), background=self.colors["accent"], foreground="#ffffff", font=(self.font_family, 10, "bold"), borderwidth=0)
        style.configure("Ghost.TButton", padding=(13, 9), background=self.colors["surface"], foreground=self.colors["ink"], font=(self.font_family, 9, "bold"), borderwidth=0)
        style.configure("Tool.TButton", padding=(11, 8), background=self.colors["panel"], foreground=self.colors["ink"], font=(self.font_family, 9), borderwidth=1, bordercolor=self.colors["line"])
        style.map("Accent.TButton", background=[("active", self.colors["accent_hot"]), ("disabled", "#1e293b")])
        style.map("Ghost.TButton", background=[("active", "#334155")])
        style.map("Tool.TButton", background=[("active", self.colors["surface"])])
        
        style.configure("TCheckbutton", background=self.colors["panel"], foreground=self.colors["ink"], font=(self.font_family, 9))
        style.map("TCheckbutton", background=[("active", self.colors["panel"])], foreground=[("active", self.colors["ink"])])
        style.configure("TEntry", padding=(10, 8), fieldbackground="#1f2937", foreground=self.colors["ink"], insertcolor=self.colors["ink"], bordercolor=self.colors["line"])
        style.configure("Horizontal.TProgressbar", background=self.colors["green"], troughcolor="#1e293b", bordercolor="#1e293b", lightcolor=self.colors["green"], darkcolor=self.colors["green"])
        
        style.configure("Treeview", rowheight=34, background=self.colors["panel"], fieldbackground=self.colors["panel"], foreground=self.colors["ink"], borderwidth=0, font=(self.font_family, 10))
        style.configure("Treeview.Heading", background=self.colors["surface"], foreground=self.colors["ink"], font=(self.font_family, 9, "bold"), relief="flat")
        style.map("Treeview.Heading", background=[("active", self.colors["line"])])
        style.map("Treeview", background=[("selected", self.colors["accent"])], foreground=[("selected", "#ffffff")])

    def _text(self, parent: tk.Widget, text: str, size: int, weight: str = "normal", bg: str | None = None, fg: str | None = None) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            bg=bg or self.colors["panel"],
            fg=fg or self.colors["ink"],
            font=(self.font_family, size, weight),
            anchor="w",
            justify="left",
        )

    def _panel(self, parent: tk.Widget, **grid_options: object) -> tk.Frame:
        outer = tk.Frame(parent, bg=self.colors["line"], padx=1, pady=1)
        outer.grid(**grid_options)
        inner = tk.Frame(outer, bg=self.colors["panel"], padx=18, pady=18)
        inner.pack(fill="both", expand=True)
        return inner

    def _build(self) -> None:
        page = ttk.Frame(self, padding=0, style="Shell.TFrame")
        page.pack(fill="both", expand=True)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(0, weight=1)

        sidebar = tk.Frame(page, bg=self.colors["nav"], width=260, padx=24, pady=24)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        self._text(sidebar, "XML", 12, "bold", bg=self.colors["nav"], fg="#93c5fd").pack(anchor="w")
        self._text(sidebar, "Feed Merger", 25, "bold", bg=self.colors["nav"], fg=self.colors["nav_text"]).pack(anchor="w", pady=(4, 8))
        sidebar_intro = self._text(sidebar, "Merge, dedupe, and validate feeds without babysitting the pipeline.", 10, bg=self.colors["nav"], fg=self.colors["nav_muted"])
        sidebar_intro.configure(wraplength=205)
        sidebar_intro.pack(anchor="w", fill="x")

        nav_block = tk.Frame(sidebar, bg=self.colors["nav_soft"], padx=16, pady=14)
        nav_block.pack(fill="x", pady=(34, 0))
        self.status = tk.StringVar(value="Ready")
        self._text(nav_block, "Status", 9, "bold", bg=self.colors["nav_soft"], fg=self.colors["nav_muted"]).pack(anchor="w")
        tk.Label(nav_block, textvariable=self.status, bg=self.colors["nav_soft"], fg=self.colors["nav_text"], font=(self.font_family, 16, "bold"), anchor="w").pack(anchor="w", pady=(3, 0))
        self.sidebar_count = tk.StringVar(value="0 sources")
        tk.Label(nav_block, textvariable=self.sidebar_count, bg=self.colors["nav_soft"], fg="#93c5fd", font=(self.font_family, 10, "bold"), anchor="w").pack(anchor="w", pady=(12, 0))

        footer = tk.Frame(sidebar, bg=self.colors["nav"])
        footer.pack(side="bottom", fill="x")
        self._text(footer, "Streaming XML engine", 9, "bold", bg=self.colors["nav"], fg=self.colors["nav_muted"]).pack(anchor="w")
        footer_note = self._text(footer, "Heavy libraries load only when a merge starts, so the app opens quickly.", 9, bg=self.colors["nav"], fg="#7c8797")
        footer_note.configure(wraplength=205)
        footer_note.pack(anchor="w", pady=(4, 0), fill="x")

        content = ttk.Frame(page, padding=22, style="Shell.TFrame")
        content.grid(row=0, column=1, sticky="nsew")
        content.columnconfigure(0, weight=5)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=0)
        content.rowconfigure(1, weight=1)
        content.rowconfigure(2, weight=1)
        content.rowconfigure(3, weight=0)

        header = tk.Frame(content, bg=self.colors["bg"])
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)
        self._text(header, "Workspace", 22, "bold", bg=self.colors["bg"]).grid(row=0, column=0, sticky="w")
        self._text(header, "Add sources, choose output, then run the merger.", 10, bg=self.colors["bg"], fg=self.colors["muted"]).grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.run_button = ttk.Button(header, text="Run merger", style="Accent.TButton", command=self._start)
        self.run_button.grid(row=0, column=1, rowspan=2, sticky="e", padx=(18, 0))

        feeds = self._panel(content, row=1, column=0, rowspan=2, sticky="nsew", padx=(0, 16))
        feeds.columnconfigure(0, weight=1)
        feeds.rowconfigure(1, weight=1)
        feed_head = tk.Frame(feeds, bg=self.colors["panel"])
        feed_head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        feed_head.columnconfigure(0, weight=1)
        self._text(feed_head, "Feed sources", 14, "bold").grid(row=0, column=0, sticky="w")
        self.count = tk.Label(feed_head, text="", bg=self.colors["surface"], fg="#60a5fa", padx=10, pady=4, font=(self.font_family, 9, "bold"))
        self.count.grid(row=0, column=1, sticky="e")
        self.sources = ttk.Treeview(feeds, columns=("source",), show="headings", selectmode="extended")
        self.sources.heading("source", text="URL or local XML file")
        self.sources.column("source", width=720, anchor="w")
        self.sources.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(feeds, orient="vertical", command=self.sources.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.sources.configure(yscrollcommand=scroll.set)
        actions = tk.Frame(feeds, bg=self.colors["panel"])
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        for label, command in (("Add URL", self._add_url), ("Add files", self._add_files), ("Remove", self._remove), ("Clear", self._clear)):
            ttk.Button(actions, text=label, style="Ghost.TButton", command=command).pack(side="left", padx=(0, 8))

        settings = self._panel(content, row=1, column=1, sticky="new")
        settings.columnconfigure(1, weight=1)
        self._text(settings, "Output", 14, "bold").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        ttk.Label(settings, text="Merged XML", style="Panel.TLabel").grid(row=1, column=0, sticky="w")
        self.output = tk.StringVar(value=str(self.base.output_file))
        ttk.Entry(settings, textvariable=self.output).grid(row=1, column=1, sticky="ew", padx=10)
        ttk.Button(settings, text="Browse", style="Ghost.TButton", command=self._choose_output).grid(row=1, column=2)
        self.delete_temp = tk.BooleanVar(value=self.base.delete_temp_files)
        self.reset_db = tk.BooleanVar(value=self.base.reset_duplicate_db)
        ttk.Checkbutton(settings, text="Delete downloaded temporary files", variable=self.delete_temp).grid(row=2, column=1, columnspan=2, sticky="w", pady=(14, 0))
        ttk.Checkbutton(settings, text="Start with a fresh duplicate index", variable=self.reset_db).grid(row=3, column=1, columnspan=2, sticky="w", pady=(6, 0))
        self.progress = ttk.Progressbar(settings, mode="indeterminate")
        self.progress.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(18, 10))

        summary = self._panel(content, row=2, column=1, sticky="nsew", pady=(16, 0))
        self._text(summary, "Last run", 14, "bold").pack(anchor="w", pady=(0, 12))
        self.metrics = {key: tk.StringVar(value="-") for key in ("Feeds", "Jobs written", "Duplicates", "Elapsed")}
        for key, value in self.metrics.items():
            row = tk.Frame(summary, bg=self.colors["bg"], padx=12, pady=8)
            row.pack(fill="x", pady=4)
            self._text(row, key, 9, "bold", bg=self.colors["bg"], fg=self.colors["muted"]).pack(anchor="w")
            tk.Label(row, textvariable=value, bg=self.colors["bg"], fg=self.colors["ink"], font=(self.font_family, 16, "bold"), anchor="w").pack(anchor="w", pady=(2, 0))

        # Real-time Gauge Canvas widget
        self.gauge_canvas = tk.Canvas(summary, width=200, height=110, bg=self.colors["panel"], highlightthickness=0)
        self.gauge_canvas.pack(pady=(16, 0))
        self._draw_gauge(0.0)

        activity = self._panel(content, row=3, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        activity.columnconfigure(0, weight=1)
        activity.rowconfigure(0, weight=1)
        self._text(activity, "Activity log", 14, "bold").grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.activity = tk.Text(activity, state="disabled", wrap="word", height=7, borderwidth=0, padx=14, pady=12, bg=self.colors["log"], fg="#dbeafe", insertbackground="#dbeafe", font=(self.mono_family, 9))
        self.activity.grid(row=1, column=0, sticky="ew")
        activity_scroll = ttk.Scrollbar(activity, orient="vertical", command=self.activity.yview)
        activity_scroll.grid(row=1, column=1, sticky="ns")
        self.activity.configure(yscrollcommand=activity_scroll.set)

    def _draw_gauge(self, speed: float) -> None:
        self.gauge_canvas.delete("all")
        # Draw background arc
        self.gauge_canvas.create_arc(
            15, 20, 185, 190,
            start=0,
            extent=180,
            style="arc",
            outline=self.colors["line"],
            width=12
        )
        # Scaled active arc (up to 500 jobs/sec)
        max_speed = 500.0
        ratio = min(speed / max_speed, 1.0)
        extent = 180.0 * ratio

        if extent > 0:
            color = self.colors["green"] if speed >= 300 else self.colors["accent"]
            self.gauge_canvas.create_arc(
                15, 20, 185, 190,
                start=180,
                extent=-extent,
                style="arc",
                outline=color,
                width=12
            )
        # Numerical speed value
        self.gauge_canvas.create_text(
            100, 72,
            text=f"{speed:.1f}",
            fill=self.colors["ink"],
            font=(self.font_family, 18, "bold")
        )
        self.gauge_canvas.create_text(
            100, 92,
            text="jobs / sec",
            fill=self.colors["muted"],
            font=(self.font_family, 9, "bold")
        )

    def _load_sources(self) -> None:
        if self.base.feeds_file.exists():
            for line in self.base.feeds_file.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.lstrip().startswith("#"):
                    self._insert(line.strip())
        self._update_count()

    def _insert(self, source: str) -> None:
        if source not in self.source_values:
            self.source_values.add(source)
            self.sources.insert("", "end", values=(source,))

    def _add_url(self) -> None:
        source = simpledialog.askstring("Add feed URL", "Feed URL (http:// or https://):", parent=self)
        if source:
            if source.strip().startswith(("http://", "https://")):
                self._insert(source.strip())
                self._update_count()
            else:
                messagebox.showerror("Invalid URL", "Enter a URL beginning with http:// or https://.", parent=self)

    def _add_files(self) -> None:
        for path in filedialog.askopenfilenames(title="Select XML feeds", filetypes=[("XML feeds", "*.xml *.gz"), ("All files", "*.*")]):
            self._insert(path)
        self._update_count()

    def _remove(self) -> None:
        for item in self.sources.selection():
            values = self.sources.item(item, "values")
            if values:
                self.source_values.discard(values[0])
            self.sources.delete(item)
        self._update_count()

    def _clear(self) -> None:
        for item in self.sources.get_children():
            self.sources.delete(item)
        self.source_values.clear()
        self._update_count()

    def _update_count(self) -> None:
        count = len(self.sources.get_children())
        self.count.config(text=f"{count} source{'s' if count != 1 else ''}")
        self.sidebar_count.set(f"{count} source{'s' if count != 1 else ''}")

    def _choose_output(self) -> None:
        path = filedialog.asksaveasfilename(title="Save merged XML", defaultextension=".xml", filetypes=[("XML", "*.xml"), ("All files", "*.*")], initialfile=Path(self.output.get()).name)
        if path:
            self.output.set(path)

    def _start(self) -> None:
        values = [self.sources.item(item, "values")[0] for item in self.sources.get_children()]
        text = self.output.get().strip()
        if not values or not text:
            messagebox.showwarning("Details required", "Add at least one source and select an output file.", parent=self)
            return
        self.base.feeds_file.write_text("\n".join(values) + "\n", encoding="utf-8")
        output = Path(text)
        config = MergerConfig(feeds_file=self.base.feeds_file, output_file=output, duplicate_db=output.parent / "duplicates.sqlite3", statistics_file=output.parent / "statistics.json", delete_temp_files=self.delete_temp.get(), reset_duplicate_db=self.reset_db.get())
        self.run_button.config(state="disabled")
        self.progress.start(12)
        self.status.set("Merge in progress")
        self._log("Starting merge...")
        self._draw_gauge(0.0)
        self.worker_thread = threading.Thread(target=self._worker, args=(config,), daemon=True)
        self.worker_thread.start()

    def _worker(self, config: MergerConfig) -> None:
        from core.logger import configure_logging
        from core.merger import FeedMerger

        handler = QueueHandler(self.log_queue)
        root = logging.getLogger()
        try:
            configure_logging(config.logs_dir / "merger.log")
            root.addHandler(handler)
            merger = FeedMerger(config)

            async def publish_stats():
                try:
                    while True:
                        await asyncio.sleep(0.2)
                        self.result_queue.put(("progress", merger.statistics.snapshot()))
                except asyncio.CancelledError:
                    pass

            async def run_merger_with_stats():
                task = asyncio.create_task(publish_stats())
                try:
                    await merger.run(config.feeds_file)
                finally:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

            asyncio.run(run_merger_with_stats())
            self.result_queue.put(("done", merger.statistics.snapshot()))
        except Exception as error:
            self.result_queue.put(("error", str(error)))
        finally:
            root.removeHandler(handler)

    def _poll(self) -> None:
        while not self.log_queue.empty():
            self._log(self.log_queue.get_nowait())
        while not self.result_queue.empty():
            kind, result = self.result_queue.get_nowait()
            if kind == "progress":
                stats = result
                self.metrics["Feeds"].set(f"{stats['successful_feeds']} succeeded, {stats['failed_feeds']} failed")
                self.metrics["Jobs written"].set(str(stats["jobs_written"]))
                self.metrics["Duplicates"].set(str(stats["duplicates_removed"]))
                self.metrics["Elapsed"].set(f"{stats['elapsed_seconds']:.2f}s")
                self._draw_gauge(stats["jobs_per_second"])
            elif kind == "done":
                stats = result
                self.run_button.config(state="normal")
                self.progress.stop()
                self.status.set("Completed")
                self.metrics["Feeds"].set(f"{stats['successful_feeds']} succeeded, {stats['failed_feeds']} failed")
                self.metrics["Jobs written"].set(str(stats["jobs_written"]))
                self.metrics["Duplicates"].set(str(stats["duplicates_removed"]))
                self.metrics["Elapsed"].set(f"{stats['elapsed_seconds']:.2f}s")
                self._draw_gauge(stats["jobs_per_second"])
                self._log("Merge completed successfully.")
                messagebox.showinfo("Success", f"Merged {stats['jobs_written']} jobs successfully!", parent=self)
            elif kind == "error":
                self.run_button.config(state="normal")
                self.progress.stop()
                self.status.set("Failed")
                self._log(f"ERROR  {result}")
                self._draw_gauge(0.0)
                messagebox.showerror("Merge failed", str(result), parent=self)
        self.after(100, self._poll)

    def _log(self, message: str) -> None:
        self.activity.config(state="normal")
        self.activity.insert("end", f"{message}\n")
        self.activity.see("end")
        self.activity.config(state="disabled")

    def _on_close(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            if not messagebox.askyesno(
                "Exit?",
                "A merge is currently in progress. Exiting may corrupt your files or database. Exit anyway?",
                parent=self,
            ):
                return
        self.destroy()


def launch(config: MergerConfig | None = None) -> None:
    FeedMergerApp(config).mainloop()
