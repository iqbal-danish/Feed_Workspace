"""
MainWindow hosting QWebEngineView and registering QWebChannel Bridge.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QSettings, QUrl, Slot, Signal, QThread
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QWidget

from validator.models import AppSettings, FileInfo, ValidationError, ValidationProgress, ValidationResult
from validator.report_generator import ReportGenerator
from workers.validation_worker import ValidationWorker
from utils.file_utils import open_containing_folder

logger = logging.getLogger("xml_validator_pro.main_window")


class CustomWebEnginePage(QWebEnginePage):
    """Custom QWebEnginePage subclass that redirects console messages to python logs."""

    def javaScriptConsoleMessage(self, level, message, line, source) -> None:
        try:
            with open(r"C:\Users\diqbal\OneDrive - CareerBuilder\Python\Feed_Utils\js_console.log", "a", encoding="utf-8") as f:
                f.write(f"[{level}] {source}:{line} -> {message}\n")
        except Exception:
            pass
        logger.info("JS Console: %s:%s -> %s", source, line, message)


class CustomWebEngineView(QWebEngineView):
    """Custom QWebEngineView subclass that intercepts drag & drop events."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPage(CustomWebEnginePage(self))
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept files dragged over the view."""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if len(urls) == 1:
                path = Path(urls[0].toLocalFile())
                if path.suffix.lower() in (".xml", ".json", ".xsd", ".xsl", ".xslt", ".svg", ".xhtml"):
                    event.acceptProposedAction()
                    return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        """Handle drops directly on the web view."""
        urls = event.mimeData().urls()
        if urls:
            path_str = str(Path(urls[0].toLocalFile()).resolve()).replace("\\", "/")
            main_window = self.window()
            if isinstance(main_window, MainWindow):
                main_window._settings.add_recent_file(path_str)
                main_window._save_settings()
                main_window.bridge.recent_files_updated.emit(json.dumps(main_window._settings.recent_files))
                # Forward to browser JS
                self.page().runJavaScript(f"window.selectFile('{path_str}');")
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class Bridge(QObject):
    """Bridge object exposed to JavaScript page for bi-directional communication."""

    # ── Signals (Serialized as JSON strings to avoid Shiboken conversion errors) ───
    file_info_ready = Signal(str)
    progress_updated = Signal(str)
    error_found = Signal(str)
    validation_complete = Signal(str)
    validation_failed = Signal(str)
    recent_files_updated = Signal(str)

    def __init__(self, parent: MainWindow) -> None:
        super().__init__(parent)
        self._main_window = parent

    @Slot(result=str)
    def load_settings(self) -> str:
        """Called by Javascript on load to fetch app settings and history."""
        settings = self._main_window._settings
        return json.dumps({
            "context_line_count": settings.context_line_count,
            "theme": settings.theme,
            "font_size": settings.font_size,
            "recent_files": settings.recent_files,
        })

    @Slot(str, object)
    def save_setting(self, key: str, value: any) -> None:
        """Store individual setting configuration values."""
        settings = self._main_window._settings
        if key == "theme":
            settings.theme = str(value)
        elif key == "context_line_count":
            settings.context_line_count = int(value)
        self._main_window._save_settings()

    @Slot(result=str)
    def open_file_dialog(self) -> str:
        """Trigger native browse file dialog."""
        file_path, _ = QFileDialog.getOpenFileName(
            self._main_window,
            "Select XML or JSON Document",
            "",
            "Documents (*.xml *.json *.xsd *.xsl *.xslt *.svg *.xhtml);;All Files (*)"
        )
        if file_path:
            self._main_window._settings.add_recent_file(file_path)
            self._main_window._save_settings()
            self.recent_files_updated.emit(json.dumps(self._main_window._settings.recent_files))
            return file_path
        return ""

    @Slot(str, int)
    def start_validation(self, file_path_or_url: str, context_lines: int) -> None:
        """Spawn background validation thread on demand."""
        self._main_window.start_validation(file_path_or_url, context_lines)

    @Slot()
    def cancel_validation(self) -> None:
        """Cancel validation worker."""
        self._main_window.cancel_validation()

    @Slot()
    def show_export_dialog(self) -> None:
        """Display native save file dialog to export reports in various formats."""
        self._main_window.show_export_dialog()

    @Slot()
    def clear_recent_files(self) -> None:
        """Clear all recent files from history and persist the change."""
        self._main_window._settings.recent_files = []
        self._main_window._save_settings()
        self.recent_files_updated.emit(json.dumps([]))


class MainWindow(QMainWindow):
    """Main window embedding the Chromium WebView dashboard."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("XML & JSON Validator Pro")
        self.setMinimumSize(1200, 800)
        self.setAcceptDrops(True)

        self._active_path: str | None = None
        self._last_result: ValidationResult | None = None
        self._validation_thread: QThread | None = None
        self._worker: ValidationWorker | None = None
        self._settings = AppSettings()

        self._init_settings()
        self._init_ui()

    def _init_settings(self) -> None:
        """Load and restore settings attributes."""
        q_settings = QSettings("XMLValidatorPro", "XMLValidatorPro")
        self._settings.context_line_count = int(q_settings.value("context_line_count", 10))
        self._settings.theme = str(q_settings.value("theme", "dark"))
        self._settings.font_size = int(q_settings.value("font_size", 12))
        
        recent = q_settings.value("recent_files")
        if isinstance(recent, list):
            self._settings.recent_files = [str(r) for r in recent]
        else:
            self._settings.recent_files = []

        geom = q_settings.value("window_geometry")
        if geom:
            self.restoreGeometry(geom)

    def _save_settings(self) -> None:
        """Write setting parameters to registry."""
        q_settings = QSettings("XMLValidatorPro", "XMLValidatorPro")
        q_settings.setValue("context_line_count", self._settings.context_line_count)
        q_settings.setValue("theme", self._settings.theme)
        q_settings.setValue("recent_files", self._settings.recent_files)
        q_settings.setValue("window_geometry", self.saveGeometry())

    def _init_ui(self) -> None:
        """Create WebView and QWebChannel connection."""
        self.web_view = CustomWebEngineView(self)
        self.setCentralWidget(self.web_view)

        # Allow local file access and scrollbar aesthetics
        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, True)

        # Setup channel
        self.channel = QWebChannel()
        self.bridge = Bridge(self)
        self.channel.registerObject("pyBridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)

        # Load web page
        resources_dir = Path(__file__).parent / "resources"
        index_path = resources_dir / "index.html"
        self.web_view.load(QUrl.fromLocalFile(index_path))

    def load_file(self, file_path: Path) -> None:
        """Load a file passed from CLI or native trigger."""
        path_str = str(file_path.resolve()).replace("\\", "/")
        
        def on_load_finished(ok):
            if ok:
                self.web_view.page().runJavaScript(f"window.selectFile('{path_str}');")
                
        self.web_view.loadFinished.connect(on_load_finished)
        self.web_view.page().runJavaScript(f"window.selectFile('{path_str}');")

    # ── Thread Orchestration ──────────────────────────────────────────────────

    def start_validation(self, file_path_or_url: str, context_lines: int) -> None:
        """Start thread processing on the specified file or URL."""
        self._active_path = file_path_or_url
        self._last_result = None

        self._validation_thread = QThread()
        self._worker = ValidationWorker()
        self._worker.set_file(Path(file_path_or_url) if not file_path_or_url.startswith(("http://", "https://")) else file_path_or_url, context_lines)
        self._worker.moveToThread(self._validation_thread)

        # Connect signals
        self._validation_thread.started.connect(self._worker.run)
        
        self._worker.file_info_ready.connect(lambda info: self.bridge.file_info_ready.emit(json.dumps(info.to_dict())))
        
        # Convert objects to dicts for JS
        self._worker.progress_updated.connect(lambda progress: self.bridge.progress_updated.emit(json.dumps({
            "bytes_processed": progress.bytes_processed,
            "total_bytes": progress.total_bytes,
            "current_line": progress.current_line,
            "percent_complete": progress.percent_complete,
            "elapsed_seconds": progress.elapsed_seconds,
            "estimated_remaining_seconds": progress.estimated_remaining_seconds,
            "processing_speed_mbps": progress.processing_speed_mbps,
            "errors_found": progress.errors_found
        })))
        
        self._worker.error_found.connect(lambda error: self.bridge.error_found.emit(json.dumps({
            "error_number": error.error_number,
            "line": error.line,
            "column": error.column,
            "byte_offset": error.byte_offset,
            "message": error.message,
            "category_name": error.category.value,
            "severity_name": error.severity.value,
            "context_lines": [{"line_number": cl.line_number, "text": cl.text, "is_error_line": cl.is_error_line} for cl in error.context_lines],
            "tag_name": error.tag_name,
            "reference_tag": error.reference_tag,
            "reference_line": error.reference_line,
        })))

        self._worker.validation_complete.connect(self._on_validation_complete)
        self._worker.validation_failed.connect(lambda msg: self.bridge.validation_failed.emit(msg))

        self._worker.validation_complete.connect(self._validation_thread.quit)
        self._worker.validation_complete.connect(self._worker.deleteLater)
        self._worker.validation_failed.connect(self._validation_thread.quit)
        self._worker.validation_failed.connect(self._worker.deleteLater)
        self._validation_thread.finished.connect(self._validation_thread.deleteLater)

        self._validation_thread.start()

    def cancel_validation(self) -> None:
        """Cancel active worker thread."""
        if self._worker:
            self._worker.cancel()

    def _on_validation_complete(self, result: ValidationResult) -> None:
        """Validation finished callback."""
        self._last_result = result
        self.bridge.validation_complete.emit(json.dumps({
            "duration_seconds": result.duration_seconds,
            "was_cancelled": result.was_cancelled,
            "has_errors": result.has_errors,
        }))

    # ── Report Exporter ───────────────────────────────────────────────────────

    def show_export_dialog(self) -> None:
        """Prompt users with save report options."""
        if self._last_result is None or self._active_path is None:
            return

        # Export Format Dialog
        box = QMessageBox(self)
        box.setWindowTitle("Export Report")
        box.setText("Select validation report format:")
        box.setIcon(QMessageBox.Icon.Question)
        
        btn_html = box.addButton("HTML", QMessageBox.ButtonRole.AcceptRole)
        btn_json = box.addButton("JSON", QMessageBox.ButtonRole.AcceptRole)
        btn_csv = box.addButton("CSV", QMessageBox.ButtonRole.AcceptRole)
        btn_txt = box.addButton("TXT", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)

        box.exec()
        clicked = box.clickedButton()

        fmt = ""
        if clicked == btn_html: fmt = "html"
        elif clicked == btn_json: fmt = "json"
        elif clicked == btn_csv: fmt = "csv"
        elif clicked == btn_txt: fmt = "txt"

        if not fmt:
            return

        suffix = f".{fmt}"
        default_filename = f"report_{int(result.duration_seconds if (result := self._last_result) else 0)}{suffix}"
        
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Save {fmt.upper()} Validation Report",
            default_filename,
            f"{fmt.upper()} Reports (*{suffix})"
        )

        if out_path:
            try:
                out = Path(out_path)
                if fmt == "html":
                    ReportGenerator.generate_html(self._last_result, out)
                elif fmt == "json":
                    ReportGenerator.generate_json(self._last_result, out)
                elif fmt == "csv":
                    ReportGenerator.generate_csv(self._last_result, out)
                elif fmt == "txt":
                    ReportGenerator.generate_txt(self._last_result, out)

                # Prompt user to open folder
                box_done = QMessageBox(self)
                box_done.setWindowTitle("Export Successful")
                box_done.setText(f"Validation report saved successfully:\n\n{out.name}")
                btn_open = box_done.addButton("Open Folder", QMessageBox.ButtonRole.AcceptRole)
                box_done.addButton("Close", QMessageBox.ButtonRole.RejectRole)
                box_done.exec()
                if box_done.clickedButton() == btn_open:
                    open_containing_folder(out)
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", f"Could not save report: {e}")

    def closeEvent(self, event) -> None:
        """Save settings and join worker threads cleanly."""
        if self._validation_thread and self._validation_thread.isRunning():
            self.cancel_validation()
            self._validation_thread.quit()
            self._validation_thread.wait()
        
        self._save_settings()
        event.accept()
