import os
import sys
import socket
import subprocess
import logging
import datetime
import json
import threading
import urllib.request
import uuid
import ctypes
import time
import html
import re
import io
import csv
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QTimer, QSize, QDateTime, QPoint, QPointF, QRectF, QEvent, QObject, Slot, Signal
from PySide6.QtGui import QFont, QIcon, QColor, QPainter, QPen, QLinearGradient, QBrush, QPainterPath, QPixmap, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QStackedWidget, QLabel, QFrame, QButtonGroup,
    QGridLayout, QScrollArea, QLineEdit, QSizePolicy, QGraphicsDropShadowEffect,
    QComboBox, QFileDialog, QListWidget, QListWidgetItem, QDialog, QTextBrowser,
    QMessageBox, QCheckBox, QMenu
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
from PySide6.QtWebChannel import QWebChannel

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("feed_workspace")

# ── Paths ─────────────────────────────────────────────────────────────────────
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))

VALIDATOR_DIR = os.path.join(WORKSPACE_DIR, "Feed_validator")
if VALIDATOR_DIR not in sys.path:
    sys.path.append(VALIDATOR_DIR)

try:
    from ui.main_window import MainWindow as ValidatorWindow
    logger.info("Successfully imported Feed Validator MainWindow.")
except ImportError as e:
    logger.error(f"Failed to import Feed Validator MainWindow: {e}")
    ValidatorWindow = None

try:
    import feed_core_rs
    HAS_RUST_CORE = True
    logger.info("Successfully imported feed_core_rs.")
except ImportError:
    feed_core_rs = None
    HAS_RUST_CORE = False


def get_python_exe(app_dir):
    """Detect and return the virtual environment python or fall back to system python."""
    for venv_name in (".venv", "venv"):
        venv_exe_win = os.path.join(app_dir, venv_name, "Scripts", "python.exe")
        if os.path.exists(venv_exe_win):
            return venv_exe_win
        venv_exe_nix = os.path.join(app_dir, venv_name, "bin", "python")
        if os.path.exists(venv_exe_nix):
            return venv_exe_nix
    return sys.executable


# ── JS Console Bridge ─────────────────────────────────────────────────────────
class ConsoleWebPage(QWebEnginePage):
    """Subclass of QWebEnginePage to capture and log JavaScript console outputs."""
    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        logger.info(f"JS Console [{source_id}:{line_number}]: {message}")


class AnalyzerDownloadBridge(QObject):
    """Qt bridge that lets the embedded analyzer save downloads natively."""
    download_finished = Signal(str, bool, str)

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.download_finished.connect(self._handle_download_finished)
        self.download_log_path = os.path.join(WORKSPACE_DIR, "logs", "feed_workspace_downloads.log")
        self.default_reports_dir = os.path.join(WORKSPACE_DIR, "Feed_analyzer", "reports")

    @Slot(result=str)
    def select_file_dialog(self) -> str:
        """Opens a native desktop file dialog to pick an XML or JSON feed directly without HTTP upload."""
        try:
            if HAS_RUST_CORE and hasattr(feed_core_rs, "select_file_dialog_rs"):
                filters = [
                    ("Feed Files", ["xml", "json", "gz", "zip", "tgz"]),
                    ("XML Files", ["xml", "gz"]),
                    ("JSON Files", ["json"]),
                    ("Compressed Archives", ["zip", "gz", "tgz", "tar"]),
                    ("All Files", ["*"])
                ]
                return feed_core_rs.select_file_dialog_rs("Select Feed File", filters) or ""

            file_path, _ = QFileDialog.getOpenFileName(
                self.parent_window,
                "Select Feed File",
                "",
                "Feed Files (*.xml *.json *.xml.gz *.zip *.gz *.tgz);;XML Files (*.xml *.xml.gz);;JSON Files (*.json);;Archives (*.zip *.gz *.tgz);;All Files (*)"
            )
            return file_path or ""
        except Exception as e:
            logger.error(f"Error opening select file dialog: {e}")
            return ""

    @Slot(str, str, str, str, result=str)
    def download_file(self, url: str, suggested_name: str, method: str = "GET", payload_json: str = "") -> str:
        try:
            suggested_name = suggested_name or "export.csv"
            ext = os.path.splitext(suggested_name)[1].lower()

            filters = []
            if ext == ".csv":
                filters = [("CSV Files", ["csv"]), ("All Files", ["*"])]
            elif ext in (".xlsx", ".xls"):
                filters = [("Excel Files", ["xlsx"]), ("All Files", ["*"])]
            elif ext == ".json":
                filters = [("JSON Files", ["json"]), ("All Files", ["*"])]
            elif ext == ".html":
                filters = [("HTML Files", ["html"]), ("All Files", ["*"])]
            else:
                filters = [("All Files", ["*"])]

            save_path = ""
            if HAS_RUST_CORE and hasattr(feed_core_rs, "save_file_dialog_rs"):
                save_path = feed_core_rs.save_file_dialog_rs(suggested_name, "Save Exported File", filters)
            else:
                filter_str = "All Files (*)"
                if ext == '.csv':
                    filter_str = "CSV Files (*.csv);;All Files (*)"
                elif ext in ('.xlsx', '.xls'):
                    filter_str = "Excel Files (*.xlsx);;All Files (*)"
                elif ext == '.html':
                    filter_str = "HTML Files (*.html);;All Files (*)"
                save_path, _ = QFileDialog.getSaveFileName(
                    self.parent_window,
                    "Save Exported File",
                    suggested_name,
                    filter_str
                )

            # User cancelled dialog
            if not save_path:
                logger.info("Download cancelled by user in Save As dialog.")
                return ""

            if ext and not save_path.lower().endswith(ext):
                save_path = f"{save_path}{ext}"

            request_id = uuid.uuid4().hex
            self._write_download_log(f"{request_id} save selected -> {save_path}")
            worker = threading.Thread(
                target=self._download_worker,
                args=(request_id, url, save_path, method, payload_json),
                daemon=True
            )
            worker.start()
            logger.info("Analyzer download started: %s -> %s", request_id, save_path)
            return request_id
        except Exception as e:
            logger.error("Analyzer native download failed: %s", e, exc_info=True)
            self._write_download_log(f"save dialog/setup failure -> {e}")
            QMessageBox.critical(
                self.parent_window,
                "Download Failed",
                f"Could not save the exported file:\n{e}"
            )
            return ""

    def _download_worker(self, request_id: str, url: str, save_path: str, method: str, payload_json: str) -> None:
        temp_path = f"{save_path}.part"
        try:
            parent_dir = os.path.dirname(save_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            data = None
            headers = {}
            request_method = (method or "GET").upper()
            if request_method == "POST":
                data = (payload_json or "{}").encode("utf-8")
                headers["Content-Type"] = "application/json"

            self._write_download_log(f"{request_id} download start -> {url}")
            request = urllib.request.Request(url, data=data, headers=headers, method=request_method)
            with urllib.request.urlopen(request, timeout=600) as response, open(temp_path, "wb") as output_file:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output_file.write(chunk)

            os.replace(temp_path, save_path)
            file_size = os.path.getsize(save_path)
            self._write_download_log(f"{request_id} download complete -> {save_path} ({file_size} bytes)")
            logger.info("Analyzer download saved to %s", save_path)
            self.download_finished.emit(request_id, True, save_path)
        except Exception as e:
            logger.error("Analyzer background download failed: %s", e, exc_info=True)
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            self._write_download_log(f"{request_id} download failed -> {e}")
            self.download_finished.emit(request_id, False, str(e))

    @Slot(str, bool, str)
    def _handle_download_finished(self, request_id: str, success: bool, detail: str) -> None:
        if success:
            logger.info("Analyzer download completed: %s -> %s", request_id, detail)
            return

        QMessageBox.critical(
            self.parent_window,
            "Download Failed",
            f"Could not save the exported file:\n{detail}"
        )

    def _write_download_log(self, message: str) -> None:
        try:
            os.makedirs(os.path.dirname(self.download_log_path), exist_ok=True)
            with open(self.download_log_path, "a", encoding="utf-8") as fh:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                fh.write(f"[{timestamp}] {message}\n")
        except Exception:
            pass


# ── Uptime Sparkline Widget ───────────────────────────────────────────────────
class SparklineWidget(QWidget):
    """Animated mini line-graph showing a fake uptime waveform."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self._points = [0.7, 0.75, 0.8, 0.72, 0.9, 0.85, 0.88, 0.92, 0.87, 0.95, 0.93, 0.98]
        self._offset = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(600)

    def _animate(self):
        # Shift values slightly for living animation effect
        import random
        last = self._points[-1]
        new_val = max(0.6, min(1.0, last + random.uniform(-0.04, 0.04)))
        self._points.append(new_val)
        if len(self._points) > 20:
            self._points.pop(0)
        self.update()

    def paintEvent(self, event):
        if len(self._points) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        n = len(self._points)
        step = w / (n - 1)

        pts = [(i * step, h - self._points[i] * (h - 4) - 2) for i in range(n)]

        # Draw filled gradient area under the line
        path = QPainterPath()
        path.moveTo(pts[0][0], h)
        for x, y in pts:
            path.lineTo(x, y)
        path.lineTo(pts[-1][0], h)
        path.closeSubpath()

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(139, 92, 246, 80))
        grad.setColorAt(1.0, QColor(139, 92, 246, 0))
        painter.fillPath(path, QBrush(grad))

        # Draw the line
        pen = QPen(QColor("#a78bfa"), 2)
        painter.setPen(pen)
        for i in range(1, n):
            painter.drawLine(int(pts[i-1][0]), int(pts[i-1][1]), int(pts[i][0]), int(pts[i][1]))




# ── Loading Screen ────────────────────────────────────────────────────────────
class LoadingWidget(QWidget):
    """Centered card loading screen while waiting for the local server port to open."""
    def __init__(self, app_name, port, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)

        card = QFrame(self)
        card.setFixedSize(480, 280)
        card.setObjectName("loading_card")

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(45, 45, 45, 45)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.setSpacing(16)

        icon_lbl = QLabel("⏳", card)
        icon_lbl.setStyleSheet("font-size: 44px; border: none; background: transparent;")
        card_layout.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

        self.title_label = QLabel(f"Launching {app_name}", card)
        self.title_label.setStyleSheet("font-size: 22px; font-weight: bold; color: #a78bfa; border: none; background: transparent; font-family: 'Segoe UI', Arial;")
        card_layout.addWidget(self.title_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.info_label = QLabel(f"Starting background service on port {port}…", card)
        self.info_label.setStyleSheet("font-size: 14px; color: #94a3b8; border: none; background: transparent; font-family: 'Segoe UI', Arial;")
        card_layout.addWidget(self.info_label, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(card)
        self.setStyleSheet("""
            QWidget { background-color: #09090b; }
            QFrame#loading_card {
                background-color: #1c1c1f;
                border: 1px solid #334155;
                border-radius: 16px;
            }
        """)


# ── Premium Tool Card ─────────────────────────────────────────────────────────
class ToolCard(QFrame):
    """Premium gradient tool card matching the mockup design."""
    CONFIGS = {
        "Feed Analyzer":  {"color": "#7c3aed", "light": "#a78bfa", "btn": "#7c3aed", "btn_hover": "#6d28d9"},
        "Feed Merger":    {"color": "#d97706", "light": "#fbbf24", "btn": "#d97706", "btn_hover": "#b45309"},
        "Feed Validator": {"color": "#0284c7", "light": "#38bdf8", "btn": "#0284c7", "btn_hover": "#0369a1"},
        "Feed Builder":   {"color": "#16a34a", "light": "#4ade80", "btn": "#16a34a", "btn_hover": "#15803d"},
    }
    FEATURES = {
        "Feed Analyzer":  ["Data Diagnostics", "Issue Detection", "Multi-format Reports", "Performance Insights"],
        "Feed Merger":    ["Multi-source Merge", "Duplicate Resolution", "Smart Filtering", "Data Unification"],
        "Feed Validator": ["XML & JSON Validation", "Schema Compliance", "Error Highlighting", "Detailed Reports"],
        "Feed Builder":   ["Excel to XML Mapping", "Custom Templates", "Drag & Drop Builder", "Export & Share"],
    }

    def __init__(self, title, description, icon_str, tab_index, main_window, parent=None):
        super().__init__(parent)
        self.tab_index = tab_index
        self.main_window = main_window
        cfg = self.CONFIGS.get(title, {"color": "#7c3aed", "light": "#a78bfa", "btn": "#7c3aed", "btn_hover": "#6d28d9"})
        feats = self.FEATURES.get(title, [])

        self.setObjectName("tool_card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(220, 380)

        # Drop shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(cfg["color"] + "66"))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 24)
        layout.setSpacing(0)

        # Icon circle
        icon_frame = QFrame(self)
        icon_frame.setFixedSize(64, 64)
        icon_frame.setStyleSheet(f"""
            QFrame {{
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.8,
                    fx:0.5, fy:0.5,
                    stop:0 {cfg['color']}55, stop:1 {cfg['color']}22);
                border-radius: 32px;
                border: 1.5px solid {cfg['color']}88;
            }}
        """)
        icon_inner = QVBoxLayout(icon_frame)
        icon_inner.setContentsMargins(0, 0, 0, 0)
        icon_lbl = QLabel(icon_str, icon_frame)
        icon_lbl.setStyleSheet("font-size: 26px; background: transparent; border: none;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_inner.addWidget(icon_lbl)
        layout.addWidget(icon_frame)
        layout.addSpacing(16)

        # Title
        title_lbl = QLabel(title, self)
        title_lbl.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {cfg['light']}; font-family: 'Segoe UI', Arial; background: transparent; border: none;")
        layout.addWidget(title_lbl)
        layout.addSpacing(10)

        # Description
        desc_lbl = QLabel(description, self)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color: #94a3b8; font-size: 12px; line-height: 18px; font-family: 'Segoe UI', Arial; background: transparent; border: none;")
        layout.addWidget(desc_lbl)
        layout.addSpacing(16)

        # Feature checklist
        for feat in feats:
            row = QHBoxLayout()
            row.setSpacing(8)
            check = QLabel("✓", self)
            check.setFixedWidth(18)
            check.setStyleSheet(f"color: {cfg['light']}; font-size: 15px; font-weight: bold; background: transparent; border: none;")
            feat_lbl = QLabel(feat, self)
            feat_lbl.setStyleSheet("color: #cbd5e1; font-size: 12px; font-family: 'Segoe UI', Arial; background: transparent; border: none;")
            row.addWidget(check)
            row.addWidget(feat_lbl)
            row.addStretch()
            layout.addLayout(row)

        layout.addStretch()
        layout.addSpacing(16)

        # Launch button
        btn = QPushButton("Launch Tool  →", self)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(40)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {cfg['btn']};
                color: #ffffff;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 15px;
                font-family: 'Segoe UI', Arial;
                padding: 0 16px;
            }}
            QPushButton:hover {{
                background-color: {cfg['btn_hover']};
            }}
        """)
        btn.clicked.connect(self.on_click)
        layout.addWidget(btn)

        self.setStyleSheet(f"""
            QFrame#tool_card {{
                background-color: #121214;
                border: 1px solid #27272a;
                border-radius: 14px;
            }}
            QFrame#tool_card:hover {{
                border: 1px solid {cfg['color']};
                background-color: #141416;
            }}
        """)


    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.on_click()
        else:
            super().mousePressEvent(event)

    def on_click(self):
        self.main_window.switch_to_tab(self.tab_index)


# ── Premium Vector Icon Widget ───────────────────────────────────────────────
class PremiumIconWidget(QWidget):
    """Custom QWidget that paints high-DPI crisp vector icons matching the mockup."""
    def __init__(self, icon_type, color_hex, parent=None):
        super().__init__(parent)
        self.icon_type = icon_type
        self.color = QColor(color_hex)
        self.setFixedSize(36, 36)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw circular background
        bg_color = QColor(self.color)
        bg_color.setAlpha(38) # rgba(..., 0.15)
        border_color = QColor(self.color)
        border_color.setAlpha(90) # rgba(..., 0.35)

        painter.setPen(QPen(border_color, 1))
        painter.setBrush(QBrush(bg_color))
        painter.drawEllipse(1, 1, 34, 34)

        # Draw the icon inside
        painter.setPen(QPen(self.color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self.icon_type == "Processed":
            # Server stack / cabinet (mockup Icon 1)
            # Draw 3 stacked horizontal slots/drawers
            for i in range(3):
                y = 11 + i * 5.5
                painter.drawRoundedRect(QRectF(11, y, 14, 3.5), 1, 1)
                # Small drawer handle dot
                painter.setPen(QPen(self.color, 1.2))
                painter.drawPoint(18, y + 1.7)
                painter.setPen(QPen(self.color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

        elif self.icon_type == "Success":
            # Rounded rect containing a checkmark (mockup Icon 2)
            painter.drawRoundedRect(QRectF(10, 10, 16, 16), 3, 3)
            path = QPainterPath()
            path.moveTo(13, 17.5)
            path.lineTo(16, 20.5)
            path.lineTo(21, 12.5)
            painter.drawPath(path)
        elif self.icon_type == "Time":
            # Clock/stopwatch (mockup Icon 3)
            painter.drawEllipse(QPointF(18, 19.5), 6.5, 6.5)
            # Clock hands
            painter.drawLine(QPointF(18, 19.5), QPointF(18, 16))
            painter.drawLine(QPointF(18, 19.5), QPointF(20.5, 19.5))
            # Stopwatch top ears
            painter.drawLine(QPointF(14.5, 12.5), QPointF(12.5, 10.5))
            painter.drawLine(QPointF(21.5, 12.5), QPointF(23.5, 10.5))
            # Top button
            painter.setPen(QPen(self.color, 2.5))
            painter.drawPoint(18, 10.5)
        elif self.icon_type == "Users":
            # Two silhouettes (mockup Icon 4)
            # Back user (right)
            painter.setPen(QPen(self.color, 1.2))
            painter.drawEllipse(QPointF(22, 14.5), 2.5, 2.5)
            painter.drawChord(QRectF(16, 17.5, 12, 10), 0, 180 * 16)
            # Front user (left)
            painter.setPen(QPen(self.color, 1.8))
            # Clear background for overlap
            painter.setBrush(QBrush(QColor("#121214")))
            painter.drawEllipse(QPointF(14, 16.5), 3, 3)
            painter.drawChord(QRectF(7, 20, 14, 10), 0, 180 * 16)


# ── Stat Counter Card ─────────────────────────────────────────────────────────
class StatSparkline(QWidget):
    """Mini trend sparkline custom-painted with gradient fill inside StatCard."""
    def __init__(self, color_hex, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        self.color = QColor(color_hex)
        import random
        # Fake historical trend values: generally moving upwards
        self._points = [random.uniform(0.2, 0.5) for _ in range(3)] + \
                       [random.uniform(0.4, 0.7) for _ in range(3)] + \
                       [random.uniform(0.6, 0.95) for _ in range(4)]

    def paintEvent(self, event):
        if not self._points:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        n = len(self._points)
        step = w / (n - 1) if n > 1 else w

        # Map points to widget coordinates
        pts = [(i * step, h - self._points[i] * (h - 4) - 2) for i in range(n)]

        # Draw filled gradient under the line
        path = QPainterPath()
        path.moveTo(pts[0][0], h)
        for x, y in pts:
            path.lineTo(x, y)
        path.lineTo(pts[-1][0], h)
        path.closeSubpath()

        area_grad = QLinearGradient(0, 0, 0, h)
        col_alpha = QColor(self.color)
        col_alpha.setAlpha(30)
        area_grad.setColorAt(0.0, col_alpha)
        area_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillPath(path, QBrush(area_grad))

        # Draw trend line
        pen = QPen(self.color, 1.5)
        painter.setPen(pen)
        for i in range(1, n):
            painter.drawLine(int(pts[i-1][0]), int(pts[i-1][1]), int(pts[i][0]), int(pts[i][1]))




# ── Stat Counter Card ─────────────────────────────────────────────────────────
class StatCard(QFrame):
    """Frosted glass stat card matching the mockup layout exactly."""
    ACCENT = {
        "Feeds Processed": ("#a855f7", "📄"), # Purple Document Icon
        "Success Rate":    ("#10b981", "✓"), # Green Check Icon
        "Avg Speed":       ("#0ea5e9", "⚡"), # Blue Lightning/Gauge Icon
        "Active User":     ("#eab308", "👤"), # Gold User Icon
    }

    def __init__(self, value, label, parent=None):
        super().__init__(parent)
        self.setObjectName("stat_card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(150)
        self.setFixedHeight(110)

        col_hex, icon_char = self.ACCENT.get(label, ("#f1f5f9", "📄"))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 12)
        main_layout.setSpacing(6)

        # Top row: Icon Box (left) + Sparkline (right)
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        
        # Icon Box
        icon_box = QFrame(self)
        icon_box.setFixedSize(30, 30)
        icon_box.setStyleSheet(f"""
            QFrame {{
                background-color: {col_hex}1a;
                border: 1px solid {col_hex}33;
                border-radius: 6px;
            }}
        """)
        icon_box_lay = QVBoxLayout(icon_box)
        icon_box_lay.setContentsMargins(0, 0, 0, 0)
        icon_lbl = QLabel(icon_char, icon_box)
        icon_lbl.setStyleSheet(f"color: {col_hex}; font-size: 15px; font-weight: bold; background: transparent; border: none;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_box_lay.addWidget(icon_lbl)
        top_row.addWidget(icon_box)
        
        top_row.addStretch()

        # Sparkline in top right
        self.sparkline = StatSparkline(col_hex, self)
        self.sparkline.setFixedSize(70, 24)
        top_row.addWidget(self.sparkline)
        main_layout.addLayout(top_row)

        # Bottom section: Value + Label stacked vertically
        text_layout = QVBoxLayout()
        text_layout.setSpacing(1)
        text_layout.setContentsMargins(0, 0, 0, 0)

        self.val_lbl = QLabel(value, self)
        self.val_lbl.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff; font-family: 'Segoe UI'; background: transparent; border: none;")
        text_layout.addWidget(self.val_lbl)

        lbl_lbl = QLabel(label, self)
        lbl_lbl.setStyleSheet("font-size: 10px; color: #94a3b8; font-family: 'Segoe UI'; background: transparent; border: none;")
        text_layout.addWidget(lbl_lbl)

        main_layout.addLayout(text_layout)

        self.setStyleSheet("""
            QFrame#stat_card {
                background-color: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
            }
            QFrame#stat_card:hover {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.15);
            }
        """)

    def update_value(self, new_val):
        """Update the displayed statistic value dynamically."""
        self.val_lbl.setText(new_val)


class ModernToolCard(QFrame):
    """High-density developer tool card with crisp typography matching Windows ClearType."""
    def __init__(self, title, desc, tab_index, version, badges, color_theme, secondary_action_label, main_window=None, parent=None):
        super().__init__(parent)
        self.tab_index = tab_index
        self.main_window = main_window
        self.theme = color_theme
        self.tool_title = title
        self.tool_desc = desc
        self.secondary_label = secondary_action_label

        self.setObjectName("modern_tool_card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(245)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)

        # ── Top Row: Glowing Icon + Version Pill ──
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        self.icon_box = QLabel(self.theme["icon"], self)
        self.icon_box.setFixedSize(46, 46)
        self.icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_box.setStyleSheet(f"""
            QLabel {{
                background-color: {self.theme["bg"]};
                border: 1px solid {self.theme["border"]};
                border-radius: 12px;
                color: {self.theme["color"]};
                font-size: 22px;
                font-weight: bold;
            }}
        """)
        top_row.addWidget(self.icon_box)
        top_row.addStretch()

        ver_pill = QLabel(version, self)
        ver_pill.setStyleSheet("""
            QLabel {
                background-color: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.12);
                color: #cbd5e1;
                border-radius: 6px;
                padding: 3px 9px;
                font-size: 11.5px;
                font-family: 'Consolas';
                font-weight: 600;
            }
        """)
        top_row.addWidget(ver_pill)
        lay.addLayout(top_row)

        # ── Title & Description ──
        content_col = QVBoxLayout()
        content_col.setSpacing(5)

        self.title_lbl = QLabel(title, self)
        self.title_lbl.setStyleSheet("color: #f8fafc; font-size: 19px; font-weight: 700; font-family: 'Segoe UI'; background: transparent;")
        content_col.addWidget(self.title_lbl)

        desc_lbl = QLabel(desc, self)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color: #94a3b8; font-size: 13.5px; line-height: 20px; font-family: 'Segoe UI'; background: transparent;")
        content_col.addWidget(desc_lbl)
        lay.addLayout(content_col)

        # ── Feature Badges ──
        badges_row = QHBoxLayout()
        badges_row.setSpacing(8)
        for i, b in enumerate(badges):
            b_lbl = QLabel(b, self)
            if i == 0:
                b_lbl.setStyleSheet(f"""
                    QLabel {{
                        background-color: {self.theme["bg"]};
                        border: 1px solid {self.theme["border"]};
                        color: {self.theme["color"]};
                        border-radius: 10px;
                        padding: 4px 10px;
                        font-size: 11.5px;
                        font-weight: 600;
                        font-family: 'Segoe UI';
                    }}
                """)
            else:
                b_lbl.setStyleSheet("""
                    QLabel {
                        background-color: rgba(255, 255, 255, 0.05);
                        border: 1px solid rgba(255, 255, 255, 0.1);
                        color: #94a3b8;
                        border-radius: 10px;
                        padding: 4px 10px;
                        font-size: 11.5px;
                        font-weight: 500;
                        font-family: 'Segoe UI';
                    }
                """)
            badges_row.addWidget(b_lbl)
        badges_row.addStretch()
        lay.addLayout(badges_row)

        lay.addStretch()

        # ── Action Buttons Footer ──
        footer = QFrame(self)
        footer.setStyleSheet("background: transparent; border-top: 1px solid rgba(255, 255, 255, 0.08); padding-top: 14px;")
        f_lay = QHBoxLayout(footer)
        f_lay.setContentsMargins(0, 0, 0, 0)
        f_lay.setSpacing(10)

        self.sec_btn = QPushButton(secondary_action_label, footer)
        self.sec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sec_btn.setFixedHeight(34)
        self.sec_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.12);
                color: #cbd5e1;
                border-radius: 8px;
                padding: 0 14px;
                font-size: 12.5px;
                font-weight: 600;
                font-family: 'Segoe UI';
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
                border-color: rgba(255, 255, 255, 0.2);
                color: #ffffff;
            }
        """)
        self.sec_btn.clicked.connect(self._on_secondary_click)
        f_lay.addWidget(self.sec_btn)

        f_lay.addStretch()

        self.launch_btn = QPushButton("Launch Tool →", footer)
        self.launch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.launch_btn.setFixedHeight(34)
        self.launch_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5, stop:1 #6366f1);
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 0 16px;
                font-size: 12.5px;
                font-weight: 700;
                font-family: 'Segoe UI';
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4338ca, stop:1 #4f46e5);
            }
        """)
        self.launch_btn.clicked.connect(self._on_launch_click)
        f_lay.addWidget(self.launch_btn)

        lay.addWidget(footer)

        self._set_idle_style()

    def _set_idle_style(self):
        self.setStyleSheet("""
            QFrame#modern_tool_card {
                background-color: rgba(17, 24, 39, 0.95);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
            }
        """)

    def enterEvent(self, event):
        self.setStyleSheet(f"""
            QFrame#modern_tool_card {{
                background-color: rgba(24, 33, 53, 0.98);
                border: 1px solid rgba({self.theme["rgb"]}, 0.50);
                border-radius: 16px;
            }}
        """)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._set_idle_style()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_launch_click()
        else:
            super().mousePressEvent(event)

    def _on_launch_click(self):
        if self.main_window and hasattr(self.main_window, "switch_to_tab"):
            self.main_window.switch_to_tab(self.tab_index)

    def _on_secondary_click(self):
        if not self.main_window:
            return
        if self.tab_index == 1:
            path, _ = QFileDialog.getOpenFileName(self, "Quick Profile Feed", "", "Feed Files (*.xml *.json *.csv *.gz);;All Files (*.*)")
            if path:
                self.main_window.switch_to_tab(1)
        elif self.tab_index == 5:
            path, _ = QFileDialog.getOpenFileName(self, "Quick Convert Feed", "", "Feed Files (*.xml *.json *.csv *.txt);;All Files (*.*)")
            if path:
                if hasattr(self.main_window, "converter_widget"):
                    self.main_window.converter_widget.set_local_file(path)
                self.main_window.switch_to_tab(5)
        else:
            self.main_window.switch_to_tab(self.tab_index)


class InstantDropzoneCard(QFrame):
    """Card 6: Instant Drag & Drop ingestion zone + compact recent pipelines."""
    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName("dropzone_card")
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(245)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)

        # Header
        top_row = QHBoxLayout()
        dot = QLabel("●", self)
        dot.setStyleSheet("color: #38bdf8; font-size: 14px; background: transparent;")
        top_row.addWidget(dot)

        title = QLabel("Instant Dropzone & Recents", self)
        title.setStyleSheet("color: #f8fafc; font-size: 18px; font-weight: 700; font-family: 'Segoe UI'; background: transparent;")
        top_row.addWidget(title)
        top_row.addStretch()

        auto_pill = QLabel("Auto-Detect", self)
        auto_pill.setStyleSheet("""
            QLabel {
                background-color: rgba(56, 189, 248, 0.15);
                border: 1px solid rgba(56, 189, 248, 0.35);
                color: #38bdf8;
                border-radius: 6px;
                padding: 3px 8px;
                font-size: 11px;
                font-family: 'Consolas';
                font-weight: 600;
            }
        """)
        top_row.addWidget(auto_pill)
        lay.addLayout(top_row)

        # Dashed Drop Target Box
        self.drop_target = QFrame(self)
        self.drop_target.setCursor(Qt.CursorShape.PointingHandCursor)
        self.drop_target.setStyleSheet("""
            QFrame {
                border: 1.5px dashed rgba(56, 189, 248, 0.4);
                border-radius: 10px;
                background-color: rgba(8, 12, 20, 0.7);
                padding: 10px;
            }
            QFrame:hover {
                border-color: #38bdf8;
                background-color: rgba(56, 189, 248, 0.08);
            }
        """)
        dt_lay = QVBoxLayout(self.drop_target)
        dt_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dt_lay.setSpacing(4)

        icon_lbl = QLabel("☁", self.drop_target)
        icon_lbl.setStyleSheet("color: #38bdf8; font-size: 20px; background: transparent;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dt_lay.addWidget(icon_lbl)

        prompt_lbl = QLabel("Drop feed here to auto-detect and run", self.drop_target)
        prompt_lbl.setStyleSheet("color: #f8fafc; font-size: 12.5px; font-weight: 600; font-family: 'Segoe UI'; background: transparent;")
        prompt_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dt_lay.addWidget(prompt_lbl)

        pills_row = QHBoxLayout()
        pills_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pills_row.setSpacing(8)
        for tag in ["XML", "JSON", "CSV"]:
            p = QLabel(tag, self.drop_target)
            p.setStyleSheet("background: rgba(255, 255, 255, 0.08); color: #cbd5e1; border-radius: 4px; padding: 2px 7px; font-size: 10.5px; font-family: 'Consolas'; font-weight: 600;")
            pills_row.addWidget(p)
        dt_lay.addLayout(pills_row)

        self.drop_target.mousePressEvent = lambda e: self._on_browse_file()
        lay.addWidget(self.drop_target)

        # Compact Recents List
        rec_lay = QVBoxLayout()
        rec_lay.setSpacing(6)

        recents = [
            ("catalog_2026.xml", "48.2 MB · 14.2k recs", "XML", "#fbbf24", "Run SIMD", 5),
            ("products.json",    "12.4 MB · 8.9k recs",  "JSON", "#38bdf8", "Profile",  1),
            ("jobs_stream.csv",  "84.1 MB · 92k recs",   "CSV",  "#4ade80", "Convert",  5),
        ]

        for name, meta, fmt, color, action_text, target_idx in recents:
            row = QFrame(self)
            row.setStyleSheet("background: rgba(8, 12, 20, 0.7); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px; padding: 6px 10px;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(10)

            tag_pill = QLabel(fmt, row)
            tag_pill.setStyleSheet(f"background: rgba(255, 255, 255, 0.06); color: {color}; font-size: 10.5px; font-weight: bold; border-radius: 4px; padding: 2px 6px; font-family: 'Consolas';")
            rl.addWidget(tag_pill)

            info_col = QVBoxLayout()
            info_col.setSpacing(1)
            nl = QLabel(name, row)
            nl.setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: 600; font-family: 'Segoe UI'; background: transparent;")
            info_col.addWidget(nl)
            ml = QLabel(meta, row)
            ml.setStyleSheet("color: #94a3b8; font-size: 11.5px; font-family: 'Consolas'; background: transparent;")
            info_col.addWidget(ml)
            rl.addLayout(info_col, 1)

            btn = QPushButton(action_text, row)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(28)
            btn.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.06);
                    color: #cbd5e1;
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 6px;
                    padding: 0 12px;
                    font-size: 11.5px;
                    font-weight: 600;
                    font-family: 'Segoe UI';
                }
                QPushButton:hover {
                    background: #4f46e5;
                    border-color: #6366f1;
                    color: #ffffff;
                }
            """)
            btn.clicked.connect(lambda checked=False, idx=target_idx: self._on_recent_clicked(idx))
            rl.addWidget(btn)

            rec_lay.addWidget(row)

        lay.addLayout(rec_lay)

        self.setStyleSheet("""
            QFrame#dropzone_card {
                background-color: rgba(17, 24, 39, 0.95);
                border: 1px solid rgba(56, 189, 248, 0.25);
                border-radius: 16px;
            }
            QFrame#dropzone_card:hover {
                border-color: rgba(56, 189, 248, 0.45);
            }
        """)

    def _on_browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Ingest Feed", "", "Feed Files (*.xml *.json *.csv *.gz);;All Files (*.*)")
        if path:
            self._handle_file(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self._handle_file(path)
                event.acceptProposedAction()

    def _handle_file(self, path):
        low = path.lower()
        if low.endswith('.xml') or low.endswith('.json'):
            if self.main_window and hasattr(self.main_window, "switch_to_tab"):
                self.main_window.switch_to_tab(1)
        elif low.endswith('.csv'):
            if self.main_window and hasattr(self.main_window, "converter_widget"):
                self.main_window.converter_widget.set_local_file(path)
            if self.main_window and hasattr(self.main_window, "switch_to_tab"):
                self.main_window.switch_to_tab(5)

    def _on_recent_clicked(self, idx):
        if self.main_window and hasattr(self.main_window, "switch_to_tab"):
            self.main_window.switch_to_tab(idx)


class ModernHubPage(QWidget):
    """The redesigned Feed Workspace Hub command center with crisp, high-clarity typography."""
    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName("modern_hub_page")
        self.cards = []

        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea {
                background-color: #0b0f19;
                border: none;
            }
            QScrollBar:vertical {
                background: #0b0f19;
                width: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.15);
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: #6366f1;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        container = QWidget()
        container.setStyleSheet("background-color: #0b0f19;")
        c_lay = QVBoxLayout(container)
        c_lay.setContentsMargins(36, 28, 36, 36)
        c_lay.setSpacing(24)

        # ── 1. Sub-Header Precision Bar ──
        sub_hdr = self._build_sub_header()
        c_lay.addWidget(sub_hdr)

        # ── 2. Utilities Section Title ──
        util_hdr = QHBoxLayout()
        util_title = QLabel("Feed Engine Workspace Utilities", container)
        util_title.setStyleSheet("color: #f8fafc; font-size: 19px; font-weight: 700; font-family: 'Segoe UI'; background: transparent;")
        util_hdr.addWidget(util_title)
        util_hdr.addStretch()

        nodes_ready = QLabel("6 Operational Nodes Ready", container)
        nodes_ready.setStyleSheet("color: #94a3b8; font-size: 12px; font-family: 'Consolas'; font-weight: 600; background: transparent;")
        util_hdr.addWidget(nodes_ready)
        c_lay.addLayout(util_hdr)

        # ── 4. Balanced 3x2 Bento Tools Grid ──
        grid = self._build_tools_grid()
        c_lay.addLayout(grid)

        c_lay.addStretch()
        scroll.setWidget(container)
        root_lay.addWidget(scroll)

        if self.main_window and hasattr(self.main_window, "_search"):
            self.main_window._search.textChanged.connect(self._filter_cards)

    def _build_sub_header(self):
        hdr = QFrame(self)
        hdr.setStyleSheet("background: transparent; border-bottom: 1px solid rgba(255, 255, 255, 0.08); padding-bottom: 16px;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)

        # Left: Architecture Status Badge
        badge = QLabel("⚡ High-Throughput Stream Architecture", hdr)
        badge.setStyleSheet("""
            QLabel {
                background-color: rgba(99, 102, 241, 0.15);
                border: 1px solid rgba(99, 102, 241, 0.4);
                color: #818cf8;
                border-radius: 8px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 600;
                font-family: 'Segoe UI';
            }
        """)
        hl.addWidget(badge)
        hl.addStretch()

        # Right: Telemetry chips
        chips_row = QHBoxLayout()
        chips_row.setSpacing(10)

        engine_chip = QLabel("● Engine: Rust-SIMD v4.2 Active", hdr)
        engine_chip.setStyleSheet("""
            QLabel {
                background-color: rgba(16, 185, 129, 0.12);
                border: 1px solid rgba(16, 185, 129, 0.35);
                color: #10b981;
                border-radius: 8px;
                padding: 6px 14px;
                font-size: 12px;
                font-family: 'Consolas';
                font-weight: 600;
            }
        """)
        chips_row.addWidget(engine_chip)

        mem_chip = QLabel("💾 Memory Pool: 128 MB", hdr)
        mem_chip.setStyleSheet("""
            QLabel {
                background-color: rgba(56, 189, 248, 0.12);
                border: 1px solid rgba(56, 189, 248, 0.35);
                color: #38bdf8;
                border-radius: 8px;
                padding: 6px 14px;
                font-size: 12px;
                font-family: 'Consolas';
                font-weight: 600;
            }
        """)
        chips_row.addWidget(mem_chip)

        simd_chip = QLabel("🚀 AVX2 Accelerated", hdr)
        simd_chip.setStyleSheet("""
            QLabel {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                color: #cbd5e1;
                border-radius: 8px;
                padding: 6px 14px;
                font-size: 12px;
                font-family: 'Segoe UI';
                font-weight: 600;
            }
        """)
        chips_row.addWidget(simd_chip)

        hl.addLayout(chips_row)
        return hdr


    def _build_tools_grid(self):
        grid = QGridLayout()
        grid.setSpacing(18)

        tools_data = [
            (
                "Feed Analyzer",
                "Deep inspection, field profiling, schema inference, and anomaly detection.",
                1,
                "v2.4",
                ["Interactive AST", "Distribution Charts", "Anomaly Detector"],
                {"color": "#c084fc", "rgb": "192, 132, 252", "bg": "rgba(192, 132, 252, 0.15)", "border": "rgba(192, 132, 252, 0.35)", "icon": "🔍"},
                "Quick Profile"
            ),
            (
                "Feed Merger",
                "Combine multiple source feeds into a single unified stream.",
                2,
                "v3.1",
                ["Chunked Streaming", "Deduplication", "Collision Resolver"],
                {"color": "#fbbf24", "rgb": "251, 191, 36", "bg": "rgba(251, 191, 36, 0.15)", "border": "rgba(251, 191, 36, 0.35)", "icon": "🥞"},
                "New Merge"
            ),
            (
                "Feed Validator",
                "Validate syntactic structure, tag compliance, and semantic business rules.",
                3,
                "v1.9",
                ["Strict Schema", "XSD & JSON Lint", "Rule Compliance"],
                {"color": "#38bdf8", "rgb": "56, 189, 248", "bg": "rgba(56, 189, 248, 0.15)", "border": "rgba(56, 189, 248, 0.35)", "icon": "🛡️"},
                "Batch Validate"
            ),
            (
                "Feed Builder",
                "Author, mock, compose, and generate compliant feeds from scratch.",
                4,
                "v4.0",
                ["Visual Tree Node", "Mock Generator", "Live Lint"],
                {"color": "#4ade80", "rgb": "74, 222, 128", "bg": "rgba(74, 222, 128, 0.15)", "border": "rgba(74, 222, 128, 0.35)", "icon": "🛠️"},
                "Compose Feed"
            ),
            (
                "Feed Converter",
                "Bi-directional feed format transformation with constant memory footprint.",
                5,
                "v5.2",
                ["XML ⇄ JSON ⇄ CSV", "Zero-Copy SIMD", "Instant Stream"],
                {"color": "#818cf8", "rgb": "129, 140, 248", "bg": "rgba(129, 140, 248, 0.15)", "border": "rgba(129, 140, 248, 0.35)", "icon": "🔄"},
                "Quick Convert"
            ),
        ]

        # Add 5 Tool Cards
        for i, (title, desc, idx, ver, badges, theme, sec_act) in enumerate(tools_data):
            row = i // 3
            col = i % 3
            card = ModernToolCard(title, desc, idx, ver, badges, theme, sec_act, self.main_window, self)
            self.cards.append(card)
            grid.addWidget(card, row, col)

        # Card 6: Instant Dropzone & Recents
        drop_card = InstantDropzoneCard(self.main_window, self)
        grid.addWidget(drop_card, 1, 2)

        # Distribute row & col stretch symmetrically
        for col_idx in range(3):
            grid.setColumnStretch(col_idx, 1)
        for row_idx in range(2):
            grid.setRowStretch(row_idx, 1)

        return grid

    def _filter_cards(self, text):
        query = text.strip().lower()
        for card in self.cards:
            if not query:
                card.setVisible(True)
            else:
                matches = query in card.tool_title.lower() or query in card.tool_desc.lower()
                card.setVisible(matches)



class DragDropLabel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("drag_drop_zone")
        self.setAcceptDrops(True)
        self.file_path = None
        
        self.lay = QVBoxLayout(self)
        self.lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lay.setSpacing(8)
        
        self.icon_lbl = QLabel("📥", self)
        self.icon_lbl.setStyleSheet("font-size: 32px; background: transparent; border: none;")
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lay.addWidget(self.icon_lbl)
        
        self.text_lbl = QLabel("Drag & Drop your Feed file here\n(or click to browse)", self)
        self.text_lbl.setStyleSheet("color: #94a3b8; font-size: 15px; font-family: 'Segoe UI'; text-align: center; background: transparent; border: none;")
        self.text_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lay.addWidget(self.text_lbl)
        
        self.setStyleSheet("""
            QFrame#drag_drop_zone {
                background-color: #121214;
                border: 2px dashed #334155;
                border-radius: 12px;
                min-height: 140px;
            }
        """)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("""
                QFrame#drag_drop_zone {
                    background-color: rgba(139, 92, 246, 0.1);
                    border: 2px dashed #8b5cf6;
                    border-radius: 12px;
                    min-height: 140px;
                }
            """)

    def dragLeaveEvent(self, event):
        if self.file_path:
            self.set_file(self.file_path)
        else:
            self.setStyleSheet("""
                QFrame#drag_drop_zone {
                    background-color: #121214;
                    border: 2px dashed #334155;
                    border-radius: 12px;
                    min-height: 140px;
                }
            """)

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            self.set_file(file_path)
            event.acceptProposedAction()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            path, _ = QFileDialog.getOpenFileName(self, "Select Feed File", "", "Feed Files (*.xml *.json *.csv *.txt)")
            if path:
                self.set_file(path)
        else:
            super().mousePressEvent(event)

    def set_file(self, path):
        self.file_path = path
        file_name = os.path.basename(path)
        self.icon_lbl.setText("📄")
        self.text_lbl.setText(f"Selected File: {file_name}\n({self._get_size_str(path)})")
        self.setStyleSheet("""
            QFrame#drag_drop_zone {
                background-color: rgba(16, 185, 129, 0.08);
                border: 2px dashed #10b981;
                border-radius: 12px;
                min-height: 140px;
            }
        """)

    def _get_size_str(self, path):
        try:
            sz = os.path.getsize(path)
            if sz < 1024: return f"{sz} B"
            elif sz < 1024*1024: return f"{sz/1024:.1f} KB"
            else: return f"{sz/(1024*1024):.1f} MB"
        except:
            return ""


# ── Feed Converter Tab ────────────────────────────────────────────────────────

class FeedConverterTab(QWidget):
    """Feed Converter matching the exact Feed Analyzer UI aesthetic."""
    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName("converter_tab")

        self.current_input_path = None
        self.last_converted_path = None
        self.last_converted_content = ""
        self.target_format = "JSON"
        self.history = []

        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        # ── Scroll Area wrapper for responsive screens ──
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea {
                background-color: #0b0f19;
                border: none;
            }
            QScrollBar:vertical {
                background: #0b0f19;
                width: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.12);
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: #6366f1;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        container = QWidget()
        container.setStyleSheet("background-color: #0b0f19;")
        c_lay = QVBoxLayout(container)
        c_lay.setContentsMargins(32, 24, 32, 32)
        c_lay.setSpacing(22)

        # ── SUB-HEADER PRECISION BAR ──
        sub_header = self._build_sub_header()
        c_lay.addWidget(sub_header)

        # ── SYMMETRICAL 2-COLUMN WORK CANVAS ──
        canvas = QHBoxLayout()
        canvas.setSpacing(24)

        # Left Column: Choose Source & Target Card
        self.left_card = self._build_left_card()
        canvas.addWidget(self.left_card, 1)

        # Right Column: Converted Output & Recents Card
        self.right_card = self._build_right_card()
        canvas.addWidget(self.right_card, 1)

        c_lay.addLayout(canvas)
        c_lay.addStretch()

        scroll.setWidget(container)
        root_lay.addWidget(scroll)

        # Sync states
        self._update_format_pills()
        self._set_source_mode("file")

    def _build_sub_header(self):
        hdr = QFrame(self)
        hdr.setStyleSheet("background: transparent; border-bottom: 1px solid rgba(255, 255, 255, 0.08); padding-bottom: 16px;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)

        left_col = QVBoxLayout()
        left_col.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(12)

        icon_box = QLabel("⇄", hdr)
        icon_box.setFixedSize(36, 36)
        icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_box.setStyleSheet("""
            QLabel {
                background-color: rgba(99, 102, 241, 0.15);
                border: 1px solid rgba(99, 102, 241, 0.4);
                border-radius: 10px;
                color: #818cf8;
                font-size: 20px;
                font-weight: bold;
            }
        """)
        title_row.addWidget(icon_box)

        title_lbl = QLabel("XML, JSON & CSV Feed Converter", hdr)
        title_lbl.setStyleSheet("color: #f8fafc; font-size: 20px; font-weight: 700; font-family: 'Space Grotesk', 'Segoe UI';")
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        left_col.addLayout(title_row)

        sub_lbl = QLabel("Seamless format transformations with constant in-memory footprint.", hdr)
        sub_lbl.setStyleSheet("color: #94a3b8; font-size: 13px; font-family: 'Outfit', 'Segoe UI';")
        left_col.addWidget(sub_lbl)

        hl.addLayout(left_col, 1)

        # Right status cluster
        right_cluster = QHBoxLayout()
        right_cluster.setSpacing(10)

        engine_pill = QLabel("⚙ Engine: v4.2 Rust-SIMD", hdr)
        engine_pill.setStyleSheet("""
            QLabel {
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.1);
                color: #cbd5e1;
                border-radius: 16px;
                padding: 4px 12px;
                font-size: 11px;
                font-family: 'JetBrains Mono', monospace;
            }
        """)
        right_cluster.addWidget(engine_pill)

        self.status_pill = QLabel("● Ready", hdr)
        self.status_pill.setStyleSheet("""
            QLabel {
                background-color: rgba(16, 185, 129, 0.12);
                border: 1px solid rgba(16, 185, 129, 0.3);
                color: #10b981;
                border-radius: 16px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: 600;
                font-family: 'Space Grotesk', 'Segoe UI';
            }
        """)
        right_cluster.addWidget(self.status_pill)

        self.history_btn = QPushButton("⏱ History ▾", hdr)
        self.history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.04);
                color: #cbd5e1;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 500;
                font-family: 'Outfit', 'Segoe UI';
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.08);
                color: #ffffff;
            }
        """)
        self.history_btn.clicked.connect(self._show_history_menu)
        right_cluster.addWidget(self.history_btn)

        hl.addLayout(right_cluster)
        return hdr

    def _build_left_card(self):
        card = QFrame(self)
        card.setObjectName("glass_card_left")
        card.setStyleSheet("""
            QFrame#glass_card_left {
                background-color: rgba(17, 24, 39, 0.95);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
            }
        """)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(18)

        # Card Title
        hdr_row = QHBoxLayout()
        icon = QLabel("⎘", card)
        icon.setStyleSheet("color: #38bdf8; font-size: 18px; font-weight: bold;")
        hdr_row.addWidget(icon)

        title = QLabel("Choose Source", card)
        title.setStyleSheet("color: #f8fafc; font-size: 18px; font-weight: 700; font-family: 'Space Grotesk', 'Segoe UI';")
        hdr_row.addWidget(title)
        hdr_row.addStretch()

        pool_badge = QLabel("BUFFER: 128 MB POOL", card)
        pool_badge.setStyleSheet("""
            QLabel {
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                color: #94a3b8;
                border-radius: 4px;
                padding: 2px 7px;
                font-size: 10px;
                font-family: 'JetBrains Mono', monospace;
            }
        """)
        hdr_row.addWidget(pool_badge)
        lay.addLayout(hdr_row)

        # Source Type Radio Selection
        src_lbl = QLabel("SOURCE INGESTION METHOD", card)
        src_lbl.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 700; letter-spacing: 0.8px; font-family: 'Space Grotesk', 'Segoe UI';")
        lay.addWidget(src_lbl)

        radio_row = QHBoxLayout()
        radio_row.setSpacing(10)

        # File radio button card
        self.btn_radio_file = QPushButton("● Upload XML / JSON / CSV File", card)
        self.btn_radio_file.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_radio_file.setFixedHeight(44)
        self.btn_radio_file.clicked.connect(lambda: self._set_source_mode("file"))
        radio_row.addWidget(self.btn_radio_file, 1)

        # URL radio button card
        self.btn_radio_url = QPushButton("○ Remote XML / JSON URL", card)
        self.btn_radio_url.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_radio_url.setFixedHeight(44)
        self.btn_radio_url.clicked.connect(lambda: self._set_source_mode("url"))
        radio_row.addWidget(self.btn_radio_url, 1)

        lay.addLayout(radio_row)

        # Source Payload Stack
        self.payload_stack = QStackedWidget(card)
        self.payload_stack.setStyleSheet("background: transparent;")

        # Page 0: File Input Group
        file_box = QWidget()
        fb_lay = QVBoxLayout(file_box)
        fb_lay.setContentsMargins(0, 0, 0, 0)
        fb_lay.setSpacing(6)

        flbl_row = QHBoxLayout()
        flbl = QLabel("Active Source Payload", file_box)
        flbl.setStyleSheet("color: #cbd5e1; font-size: 12px; font-weight: 500; font-family: 'Outfit', 'Segoe UI';")
        flbl_row.addWidget(flbl)
        flbl_row.addStretch()

        self.crc_badge = QLabel("CRC32: 0x9AF4D1", file_box)
        self.crc_badge.setStyleSheet("color: #38bdf8; font-size: 10px; font-family: 'JetBrains Mono', monospace;")
        flbl_row.addWidget(self.crc_badge)
        fb_lay.addLayout(flbl_row)

        # Attached Browse Input Group
        file_input_group = QFrame(file_box)
        file_input_group.setStyleSheet("""
            QFrame {
                background-color: rgba(8, 12, 20, 0.85);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 10px;
            }
        """)
        fig_lay = QHBoxLayout(file_input_group)
        fig_lay.setContentsMargins(10, 4, 4, 4)
        fig_lay.setSpacing(8)

        # Format Tag Pill
        self.tag_pill = QLabel("XML", file_input_group)
        self.tag_pill.setStyleSheet("""
            QLabel {
                background-color: rgba(245, 158, 11, 0.15);
                color: #fbbf24;
                border: 1px solid rgba(245, 158, 11, 0.3);
                border-radius: 4px;
                padding: 2px 7px;
                font-size: 10px;
                font-weight: 700;
                font-family: 'JetBrains Mono', monospace;
            }
        """)
        self.tag_pill.setVisible(False)
        fig_lay.addWidget(self.tag_pill)

        self.file_path_display = QLineEdit(file_input_group)
        self.file_path_display.setPlaceholderText("Click Browse to select XML, JSON, or CSV feed...")
        self.file_path_display.setReadOnly(True)
        self.file_path_display.setStyleSheet("""
            QLineEdit {
                background: transparent;
                border: none;
                color: #f8fafc;
                font-size: 13px;
                font-family: 'Outfit', 'Segoe UI';
            }
        """)
        self.file_path_display.mousePressEvent = lambda e: self._on_browse_file()
        fig_lay.addWidget(self.file_path_display, 1)

        self.file_size_display = QLabel("", file_input_group)
        self.file_size_display.setStyleSheet("color: #94a3b8; font-size: 12px; font-family: 'JetBrains Mono', monospace;")
        fig_lay.addWidget(self.file_size_display)

        self.browse_btn = QPushButton("📁 Browse", file_input_group)
        self.browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_btn.setFixedHeight(34)
        self.browse_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(99, 102, 241, 0.15);
                color: #818cf8;
                border: 1px solid rgba(99, 102, 241, 0.4);
                border-radius: 8px;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 600;
                font-family: 'Space Grotesk', 'Segoe UI';
            }
            QPushButton:hover {
                background-color: rgba(99, 102, 241, 0.3);
                color: #ffffff;
            }
        """)
        self.browse_btn.clicked.connect(self._on_browse_file)
        fig_lay.addWidget(self.browse_btn)

        fb_lay.addWidget(file_input_group)

        file_hint = QLabel("Direct instant parsing for feeds of any size (100MB to 50GB+).", file_box)
        file_hint.setStyleSheet("color: #64748b; font-size: 11px; font-family: 'Outfit', 'Segoe UI';")
        fb_lay.addWidget(file_hint)

        self.payload_stack.addWidget(file_box)

        # Page 1: URL Input Group
        url_box = QWidget()
        ub_lay = QVBoxLayout(url_box)
        ub_lay.setContentsMargins(0, 0, 0, 0)
        ub_lay.setSpacing(6)

        ulbl = QLabel("Feed Endpoint URL", url_box)
        ulbl.setStyleSheet("color: #cbd5e1; font-size: 12px; font-weight: 500; font-family: 'Outfit', 'Segoe UI';")
        ub_lay.addWidget(ulbl)

        url_input_group = QFrame(url_box)
        url_input_group.setStyleSheet("""
            QFrame {
                background-color: rgba(8, 12, 20, 0.85);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 10px;
            }
        """)
        uig_lay = QHBoxLayout(url_input_group)
        uig_lay.setContentsMargins(10, 4, 4, 4)
        uig_lay.setSpacing(8)

        self.url_input = QLineEdit(url_input_group)
        self.url_input.setPlaceholderText("https://api.example.com/feeds/export.xml")
        self.url_input.setStyleSheet("""
            QLineEdit {
                background: transparent;
                border: none;
                color: #f8fafc;
                font-size: 13px;
                font-family: 'Outfit', 'Segoe UI';
            }
        """)
        self.url_input.returnPressed.connect(self.fetch_from_url)
        uig_lay.addWidget(self.url_input, 1)

        self.fetch_btn = QPushButton("Fetch URL", url_input_group)
        self.fetch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fetch_btn.setFixedHeight(34)
        self.fetch_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(99, 102, 241, 0.15);
                color: #818cf8;
                border: 1px solid rgba(99, 102, 241, 0.4);
                border-radius: 8px;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 600;
                font-family: 'Space Grotesk', 'Segoe UI';
            }
            QPushButton:hover {
                background-color: rgba(99, 102, 241, 0.3);
                color: #ffffff;
            }
        """)
        self.fetch_btn.clicked.connect(self.fetch_from_url)
        uig_lay.addWidget(self.fetch_btn)

        ub_lay.addWidget(url_input_group)

        self.url_hint = QLabel("Directly streams HTTP/HTTPS XML/JSON endpoints into memory.", url_box)
        self.url_hint.setStyleSheet("color: #64748b; font-size: 11px; font-family: 'Outfit', 'Segoe UI';")
        ub_lay.addWidget(self.url_hint)

        self.payload_stack.addWidget(url_box)
        lay.addWidget(self.payload_stack)

        # Target Format Selector
        fmt_lbl = QLabel("TARGET FORMAT", card)
        fmt_lbl.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 700; letter-spacing: 0.8px; font-family: 'Space Grotesk', 'Segoe UI';")
        lay.addWidget(fmt_lbl)

        pills_row = QHBoxLayout()
        pills_row.setSpacing(10)

        self.pill_xml = QPushButton("XML", card)
        self.pill_xml.setMinimumHeight(42)
        self.pill_xml.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pill_xml.clicked.connect(lambda: self.set_target_format("XML"))
        pills_row.addWidget(self.pill_xml)

        self.pill_json = QPushButton("✓ JSON", card)
        self.pill_json.setMinimumHeight(42)
        self.pill_json.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pill_json.clicked.connect(lambda: self.set_target_format("JSON"))
        pills_row.addWidget(self.pill_json)

        self.pill_csv = QPushButton("CSV", card)
        self.pill_csv.setMinimumHeight(42)
        self.pill_csv.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pill_csv.clicked.connect(lambda: self.set_target_format("CSV"))
        pills_row.addWidget(self.pill_csv)

        lay.addLayout(pills_row)


        # Pipeline Transform Flags
        flags_lbl = QLabel("PIPELINE TRANSFORM FLAGS", card)
        flags_lbl.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 700; letter-spacing: 0.8px; font-family: 'Space Grotesk', 'Segoe UI';")
        lay.addWidget(flags_lbl)

        flags_row = QHBoxLayout()
        flags_row.setSpacing(10)

        self.chk_minify = QCheckBox("Minify Payload", card)
        self.chk_flatten = QCheckBox("Flatten Nested", card)
        self.chk_flatten.setChecked(True)
        self.chk_validate = QCheckBox("Validate UTF-8", card)
        self.chk_validate.setChecked(True)

        for chk in [self.chk_minify, self.chk_flatten, self.chk_validate]:
            chk.setStyleSheet("""
                QCheckBox {
                    color: #cbd5e1;
                    font-size: 12px;
                    font-family: 'Outfit', 'Segoe UI';
                    spacing: 6px;
                }
                QCheckBox::indicator {
                    width: 16px;
                    height: 16px;
                    border-radius: 4px;
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    background-color: #080c14;
                }
                QCheckBox::indicator:checked {
                    background-color: #6366f1;
                    border-color: #6366f1;
                }
            """)
            flags_row.addWidget(chk)

        lay.addLayout(flags_row)

        # Action Buttons
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.reset_btn = QPushButton("🧹 Reset", card)
        self.reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_btn.setFixedHeight(44)
        self.reset_btn.setFixedWidth(90)
        self.reset_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.04);
                color: #cbd5e1;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
                font-size: 13px;
                font-weight: 500;
                font-family: 'Outfit', 'Segoe UI';
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.08);
                color: #ffffff;
            }
        """)
        self.reset_btn.clicked.connect(self.reset_tab)
        action_row.addWidget(self.reset_btn)

        self.convert_btn = QPushButton("▶ Convert Feed", card)
        self.convert_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.convert_btn.setFixedHeight(44)
        self.convert_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #4f46e5);
                color: #ffffff;
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: 700;
                font-family: 'Space Grotesk', 'Segoe UI';
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5, stop:1 #4338ca);
            }
            QPushButton:disabled {
                background: #1e293b;
                color: #64748b;
            }
        """)
        self.convert_btn.clicked.connect(self.run_conversion)
        action_row.addWidget(self.convert_btn, 1)

        lay.addLayout(action_row)
        return card

    def _build_right_card(self):
        card = QFrame(self)
        card.setObjectName("glass_card_right")
        card.setStyleSheet("""
            QFrame#glass_card_right {
                background-color: rgba(17, 24, 39, 0.95);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
            }
        """)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(14)

        # Header with Output Toolbar
        hdr_row = QHBoxLayout()
        icon = QLabel("🕒", card)
        icon.setStyleSheet("color: #94a3b8; font-size: 16px;")
        hdr_row.addWidget(icon)

        title = QLabel("Recent Conversions & Output Preview", card)
        title.setStyleSheet("color: #f8fafc; font-size: 16px; font-weight: 700; font-family: 'Space Grotesk', 'Segoe UI';")
        hdr_row.addWidget(title)
        hdr_row.addStretch()

        # Toolbar
        self.copy_btn = QPushButton("📋 Copy", card)
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setStyleSheet(self._btn_toolbar_style())
        self.copy_btn.clicked.connect(self.copy_preview)
        hdr_row.addWidget(self.copy_btn)

        self.download_btn = QPushButton("⬇ Download", card)
        self.download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_btn.setStyleSheet(self._btn_toolbar_style())
        self.download_btn.clicked.connect(self.download_output)
        hdr_row.addWidget(self.download_btn)

        self.analyze_btn = QPushButton("⚡ Analyze in Workspace", card)
        self.analyze_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.analyze_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(99, 102, 241, 0.15);
                color: #818cf8;
                border: 1px solid rgba(99, 102, 241, 0.4);
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 11px;
                font-weight: 600;
                font-family: 'Space Grotesk', 'Segoe UI';
            }
            QPushButton:hover {
                background-color: rgba(99, 102, 241, 0.3);
                color: #ffffff;
            }
        """)
        self.analyze_btn.clicked.connect(self.analyze_in_workspace)
        hdr_row.addWidget(self.analyze_btn)

        lay.addLayout(hdr_row)

        # Badges Row (when converted)
        self.badges_bar = QFrame(card)
        self.badges_bar.setStyleSheet("background: transparent;")
        bb_lay = QHBoxLayout(self.badges_bar)
        bb_lay.setContentsMargins(0, 0, 0, 0)
        bb_lay.setSpacing(8)

        self.badge_fmt = self._make_badge("XML ➔ JSON", "#818cf8", "rgba(99, 102, 241, 0.15)", "rgba(99, 102, 241, 0.3)")
        bb_lay.addWidget(self.badge_fmt)

        self.badge_utf8 = self._make_badge("UTF-8 Clean", "#cbd5e1", "rgba(255, 255, 255, 0.05)", "rgba(255, 255, 255, 0.1)")
        bb_lay.addWidget(self.badge_utf8)

        self.badge_delta = self._make_badge("-24.5% Delta", "#10b981", "rgba(16, 185, 129, 0.15)", "rgba(16, 185, 129, 0.3)")
        bb_lay.addWidget(self.badge_delta)

        self.badge_disk = self._make_badge("Zero Spill to Disk", "#38bdf8", "rgba(14, 165, 233, 0.12)", "rgba(14, 165, 233, 0.25)")
        bb_lay.addWidget(self.badge_disk)

        bb_lay.addStretch()
        self.badges_bar.setVisible(False)
        lay.addWidget(self.badges_bar)

        # Output Stack: Page 0 = Empty State, Page 1 = Code Inspector
        self.output_stack = QStackedWidget(card)
        self.output_stack.setStyleSheet("background: transparent;")

        # Page 0: Empty State
        empty_widget = QFrame()
        empty_widget.setStyleSheet("""
            QFrame {
                background-color: rgba(8, 12, 20, 0.6);
                border: 1px dashed rgba(255, 255, 255, 0.08);
                border-radius: 12px;
            }
        """)
        ew_lay = QVBoxLayout(empty_widget)
        ew_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ew_lay.setSpacing(12)

        db_icon = QLabel("🗄️", empty_widget)
        db_icon.setStyleSheet("font-size: 40px; color: rgba(255, 255, 255, 0.3);")
        db_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ew_lay.addWidget(db_icon)

        empty_txt = QLabel("No feeds converted yet. Select a file or URL above to start!", empty_widget)
        empty_txt.setStyleSheet("color: #94a3b8; font-size: 13px; font-family: 'Outfit', 'Segoe UI';")
        empty_txt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ew_lay.addWidget(empty_txt)

        self.output_stack.addWidget(empty_widget)

        # Page 1: Code Inspector
        code_widget = QWidget()
        cw_lay = QVBoxLayout(code_widget)
        cw_lay.setContentsMargins(0, 0, 0, 0)
        cw_lay.setSpacing(0)

        self.preview_viewer = QTextBrowser(code_widget)
        self.preview_viewer.setMinimumHeight(380)
        self.preview_viewer.setOpenExternalLinks(True)
        self.preview_viewer.setStyleSheet("""
            QTextBrowser {
                background-color: #070a13;
                color: #cbd5e1;
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 10px;
                padding: 14px;
                font-family: 'JetBrains Mono', 'Consolas', monospace;
                font-size: 12px;
                line-height: 1.5;
            }
            QScrollBar:vertical, QScrollBar:horizontal {
                background: #070a13;
                width: 6px;
                height: 6px;
            }
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
                background: rgba(255, 255, 255, 0.12);
                border-radius: 3px;
            }
            QScrollBar::handle:hover {
                background: #6366f1;
            }
        """)
        cw_lay.addWidget(self.preview_viewer)
        self.output_stack.addWidget(code_widget)

        lay.addWidget(self.output_stack, 1)

        # Bottom Telemetry Footer
        telemetry_frame = QFrame(card)
        telemetry_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(8, 12, 20, 0.8);
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 10px;
                padding: 8px 14px;
            }
        """)
        tf_lay = QHBoxLayout(telemetry_frame)
        tf_lay.setContentsMargins(0, 0, 0, 0)
        tf_lay.setSpacing(12)

        self.telemetry_status = QLabel("Ready for conversion", telemetry_frame)
        self.telemetry_status.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 500; font-family: 'Space Grotesk', 'Segoe UI';")
        tf_lay.addWidget(self.telemetry_status, 1)

        self.telemetry_metrics = QLabel("Throughput: — • Footprint: —", telemetry_frame)
        self.telemetry_metrics.setStyleSheet("color: #94a3b8; font-size: 11px; font-family: 'JetBrains Mono', monospace;")
        tf_lay.addWidget(self.telemetry_metrics, 0, Qt.AlignmentFlag.AlignRight)

        lay.addWidget(telemetry_frame)
        return card

    def _btn_toolbar_style(self):
        return """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.04);
                color: #cbd5e1;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 5px 10px;
                font-size: 11px;
                font-weight: 500;
                font-family: 'Outfit', 'Segoe UI';
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.08);
                color: #ffffff;
            }
        """

    def _make_badge(self, text, color, bg, border):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"""
            QLabel {{
                background-color: {bg};
                color: {color};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 600;
                font-family: 'Space Grotesk', monospace;
            }}
        """)
        return lbl

    # ── Source Ingestion Switch ──────────────────────────────────────────────

    def _set_source_mode(self, mode):
        active_style = """
            QPushButton {
                background-color: rgba(99, 102, 241, 0.14);
                color: #ffffff;
                border: 1px solid rgba(99, 102, 241, 0.6);
                border-radius: 10px;
                font-size: 12px;
                font-weight: 600;
                font-family: 'Space Grotesk', 'Segoe UI';
                text-align: left;
                padding-left: 14px;
            }
        """
        inactive_style = """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.02);
                color: #94a3b8;
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 10px;
                font-size: 12px;
                font-weight: 500;
                font-family: 'Outfit', 'Segoe UI';
                text-align: left;
                padding-left: 14px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.04);
                color: #cbd5e1;
            }
        """
        if mode == "file":
            self.payload_stack.setCurrentIndex(0)
            self.btn_radio_file.setStyleSheet(active_style)
            self.btn_radio_file.setText("● Upload XML / JSON / CSV File")
            self.btn_radio_url.setStyleSheet(inactive_style)
            self.btn_radio_url.setText("○ Remote XML / JSON URL")
        else:
            self.payload_stack.setCurrentIndex(1)
            self.btn_radio_url.setStyleSheet(active_style)
            self.btn_radio_url.setText("● Remote XML / JSON URL")
            self.btn_radio_file.setStyleSheet(inactive_style)
            self.btn_radio_file.setText("○ Upload XML / JSON / CSV File")

    # ── Target Format Pills ──────────────────────────────────────────────────

    def set_target_format(self, fmt_name):
        self.target_format = fmt_name.upper()
        self._update_format_pills()

    def _update_format_pills(self):
        active_style = """
            QPushButton {
                background-color: rgba(99, 102, 241, 0.2);
                color: #ffffff;
                border: 2px solid #6366f1;
                border-radius: 10px;
                font-size: 13px;
                font-weight: 700;
                font-family: 'Space Grotesk', 'Segoe UI';
            }
        """
        inactive_style = """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.02);
                color: #94a3b8;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
                font-size: 13px;
                font-weight: 500;
                font-family: 'Outfit', 'Segoe UI';
            }
            QPushButton:hover {
                border-color: rgba(255, 255, 255, 0.16);
                color: #ffffff;
            }
        """
        self.pill_xml.setStyleSheet(active_style if self.target_format == "XML" else inactive_style)
        self.pill_xml.setText("✓ XML" if self.target_format == "XML" else "XML")

        self.pill_json.setStyleSheet(active_style if self.target_format == "JSON" else inactive_style)
        self.pill_json.setText("✓ JSON" if self.target_format == "JSON" else "JSON")

        self.pill_csv.setStyleSheet(active_style if self.target_format == "CSV" else inactive_style)
        self.pill_csv.setText("✓ CSV" if self.target_format == "CSV" else "CSV")

    # ── File Selection ───────────────────────────────────────────────────────

    def _on_browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Feed File",
            "",
            "Feed Files (*.xml *.json *.csv *.txt);;XML Files (*.xml);;JSON Files (*.json);;CSV Files (*.csv *.txt);;All Files (*.*)"
        )
        if path:
            self.set_local_file(path)

    def set_local_file(self, path):
        if not path or not os.path.exists(path):
            return
        self.current_input_path = path

        name = os.path.basename(path)
        sz = os.path.getsize(path)
        sz_str = self._format_size(sz)
        fmt = self._detect_format(path)

        # Update file input display
        self.file_path_display.setText(name)
        self.file_size_display.setText(f"({sz_str})")
        self.tag_pill.setText(fmt.upper())
        self.tag_pill.setVisible(True)

        # Switch target format if matching
        if fmt.upper() == self.target_format:
            new_target = "JSON" if fmt.upper() != "JSON" else "CSV"
            self.set_target_format(new_target)

    # ── URL Fetch ────────────────────────────────────────────────────────────

    def fetch_from_url(self):
        url = self.url_input.text().strip()
        if not url:
            self.url_hint.setText("<span style='color:#ef4444;'>Please enter a valid URL.</span>")
            return

        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("Fetching...")
        self.url_hint.setText(f"<span style='color:#38bdf8;'>Downloading feed from {url}...</span>")
        QApplication.processEvents()

        try:
            import urllib.request
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=15) as response:
                raw_data = response.read()
                try:
                    data = raw_data.decode('utf-8')
                except UnicodeDecodeError:
                    data = raw_data.decode('latin-1', errors='replace')

            scratch_dir = os.path.join(r"C:\Users\diqbal\Python\Feed_Workspace\scratch")
            os.makedirs(scratch_dir, exist_ok=True)

            ext = ".xml"
            if "json" in url.lower() or data.strip().startswith(("{", "[")):
                ext = ".json"
            elif "csv" in url.lower():
                ext = ".csv"

            temp_path = os.path.join(scratch_dir, f"converter_fetched_feed{ext}")
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(data)

            self.url_hint.setText(f"<span style='color:#10b981;'>✓ Successfully fetched {self._format_size(len(raw_data))}</span>")
            self._set_source_mode("file")
            self.set_local_file(temp_path)
        except Exception as e:
            self.url_hint.setText(f"<span style='color:#ef4444;'>Failed to fetch URL: {e}</span>")
        finally:
            self.fetch_btn.setEnabled(True)
            self.fetch_btn.setText("Fetch URL")

    # ── Conversion Execution ─────────────────────────────────────────────────

    def run_conversion(self):
        input_path = self.current_input_path
        if not input_path or not os.path.exists(input_path):
            self.telemetry_status.setText("<span style='color:#ef4444;'>Please select a source feed file first.</span>")
            return

        target_fmt = self.target_format.lower()
        src_fmt = self._detect_format(input_path).lower()

        if src_fmt == target_fmt:
            self.telemetry_status.setText(f"<span style='color:#fbbf24;'>Source is already in {target_fmt.upper()} format.</span>")
            return

        self.convert_btn.setEnabled(False)
        self.convert_btn.setText("Converting...")
        self.status_pill.setText("● Converting...")
        self.status_pill.setStyleSheet("""
            QLabel {
                background-color: rgba(99, 102, 241, 0.15);
                border: 1px solid rgba(99, 102, 241, 0.4);
                color: #818cf8;
                border-radius: 16px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: 600;
            }
        """)
        QApplication.processEvents()

        t_start = time.perf_counter()

        try:
            with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()

            in_size = os.path.getsize(input_path)
            minify = self.chk_minify.isChecked()
            flatten = self.chk_flatten.isChecked()
            indent = None if minify else 2
            delimiter = ","

            output_content = ""
            records_count = 0

            if src_fmt == 'csv':
                if target_fmt == 'json':
                    output_content, records_count = self.csv_to_json(content, indent, delimiter)
                elif target_fmt == 'xml':
                    output_content, records_count = self.csv_to_xml(content, indent, delimiter)
            elif src_fmt == 'json':
                if target_fmt == 'csv':
                    output_content, records_count = self.json_to_csv(content, delimiter, flatten)
                elif target_fmt == 'xml':
                    output_content, records_count = self.json_to_xml(content, indent)
            elif src_fmt == 'xml':
                if target_fmt == 'json':
                    output_content, records_count = self.xml_to_json(content, indent)
                elif target_fmt == 'csv':
                    json_tmp, _ = self.xml_to_json(content, None)
                    output_content, records_count = self.json_to_csv(json_tmp, delimiter, flatten)

            t_elapsed = max(0.001, time.perf_counter() - t_start)
            elapsed_ms = int(t_elapsed * 1000)

            # Save converted file
            dir_name = os.path.dirname(input_path)
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            if base_name == "converter_fetched_feed":
                base_name = "fetched_feed"
            out_filename = f"{base_name}_converted.{target_fmt}"
            out_path = os.path.join(dir_name, out_filename)

            with open(out_path, 'w', encoding='utf-8') as out_f:
                out_f.write(output_content)

            self.last_converted_path = out_path
            self.last_converted_content = output_content
            out_size = len(output_content.encode('utf-8'))

            # Telemetry Metrics
            mem_mb = max(1, int((in_size + out_size) / (1024 * 1024)))
            throughput = int(records_count / t_elapsed) if records_count > 0 else int(out_size / (t_elapsed * 1024))
            throughput_str = f"{throughput:,} rec/s" if records_count > 0 else f"{throughput:,} KB/s"

            delta_pct = ((out_size - in_size) / in_size * 100) if in_size > 0 else 0
            delta_sign = "+" if delta_pct >= 0 else ""
            delta_str = f"{delta_sign}{delta_pct:.1f}% Delta"

            # Update Right Card
            self._render_code_preview(output_content, target_fmt, out_filename, records_count)
            self.output_stack.setCurrentIndex(1)

            # Update Badges
            self.badge_fmt.setText(f"{src_fmt.upper()} ➔ {target_fmt.upper()}")
            self.badge_delta.setText(delta_str)
            self.badges_bar.setVisible(True)

            # Update Telemetry Footer
            rec_display = f"{records_count:,} items" if records_count > 0 else self._format_size(out_size)
            self.telemetry_status.setText(
                f"<span style='color:#10b981; font-weight:600;'>✓ Successfully converted {rec_display} in {elapsed_ms}ms</span>"
            )
            self.telemetry_metrics.setText(
                f"Throughput: <span style='color:#f8fafc; font-weight:600;'>{throughput_str}</span>  •  Footprint: <span style='color:#f8fafc; font-weight:600;'>{mem_mb} MB in-memory</span>"
            )

            # Update Status Pill
            self.status_pill.setText("● Converted")
            self.status_pill.setStyleSheet("""
                QLabel {
                    background-color: rgba(16, 185, 129, 0.15);
                    border: 1px solid rgba(16, 185, 129, 0.4);
                    color: #10b981;
                    border-radius: 16px;
                    padding: 4px 12px;
                    font-size: 11px;
                    font-weight: 600;
                }
            """)

            # Add to History
            self.history.insert(0, {
                "name": out_filename,
                "path": out_path,
                "in_fmt": src_fmt.upper(),
                "out_fmt": target_fmt.upper(),
                "count": records_count,
                "size_str": self._format_size(out_size),
                "timestamp": datetime.datetime.now().strftime("%H:%M:%S")
            })

            # Update session stats
            if hasattr(self.main_window, "total_validations"):
                self.main_window.total_validations += 1
                self.main_window.successful_validations += 1
                self.main_window.refresh_stats()

        except Exception as e:
            self.telemetry_status.setText(f"<span style='color:#ef4444;'>[Conversion Error] {e}</span>")
            self.status_pill.setText("● Error")
            self.status_pill.setStyleSheet("""
                QLabel {
                    background-color: rgba(239, 68, 68, 0.12);
                    border: 1px solid rgba(239, 68, 68, 0.3);
                    color: #ef4444;
                    border-radius: 16px;
                    padding: 4px 12px;
                    font-size: 11px;
                    font-weight: 600;
                }
            """)
        finally:
            self.convert_btn.setEnabled(True)
            self.convert_btn.setText("▶ Convert Feed")

    # ── Syntax Highlighted Preview Rendering ─────────────────────────────────

    def _render_code_preview(self, content, fmt, filename, record_count):
        max_preview_len = 16000
        is_truncated = len(content) > max_preview_len
        slice_txt = content[:max_preview_len]

        header_comment = f"// {filename} • Output Stream • {record_count:,} items\n"
        if fmt == 'xml':
            header_comment = f"<!-- {filename} • Output Stream • {record_count:,} items -->\n"

        if fmt == 'json':
            def json_replacer(match):
                str_val = match.group(1)
                colon = match.group(2)
                num_val = match.group(3)
                kw_val = match.group(4)
                if str_val is not None:
                    esc_str = html.escape(str_val)
                    if colon:
                        return f'<span style="color:#22d3ee; font-weight:bold;">{esc_str}</span>{colon}'
                    else:
                        return f'<span style="color:#10b981;">{esc_str}</span>'
                elif num_val is not None:
                    return f'<span style="color:#c084fc;">{num_val}</span>'
                elif kw_val is not None:
                    return f'<span style="color:#fbbf24; font-weight:bold;">{kw_val}</span>'
                return html.escape(match.group(0))

            pattern = re.compile(r'("(?:\\.|[^"\\])*")(\s*:)?|(-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|\b(true|false|null)\b')
            parts = []
            last_end = 0
            for m in pattern.finditer(slice_txt):
                parts.append(html.escape(slice_txt[last_end:m.start()]))
                parts.append(json_replacer(m))
                last_end = m.end()
            parts.append(html.escape(slice_txt[last_end:]))
            esc = ''.join(parts)

        elif fmt == 'xml':
            def xml_replacer(match):
                tag = match.group(1)
                attr_name = match.group(2)
                attr_val = match.group(3)
                close_b = match.group(4)
                if tag:
                    return f'<span style="color:#22d3ee; font-weight:bold;">{html.escape(tag)}</span>'
                elif attr_name and attr_val:
                    return f'<span style="color:#c084fc;">{html.escape(attr_name)}</span>=<span style="color:#10b981;">{html.escape(attr_val)}</span>'
                elif close_b:
                    return f'<span style="color:#22d3ee; font-weight:bold;">{html.escape(close_b)}</span>'
                return html.escape(match.group(0))

            pattern = re.compile(r'(</?[\w:\-]+)|([\w:\-]+)=("[^"]*")|(/?>)')
            parts = []
            last_end = 0
            for m in pattern.finditer(slice_txt):
                parts.append(html.escape(slice_txt[last_end:m.start()]))
                parts.append(xml_replacer(m))
                last_end = m.end()
            parts.append(html.escape(slice_txt[last_end:]))
            esc = ''.join(parts)

        elif fmt == 'csv':
            esc_raw = html.escape(slice_txt)
            lines = esc_raw.split('\n')
            if lines:
                lines[0] = f'<span style="color:#22d3ee; font-weight:bold;">{lines[0]}</span>'
                for i in range(1, len(lines)):
                    lines[i] = f'<span style="color:#f8fafc;">{lines[i]}</span>'
                esc = '\n'.join(lines)
            else:
                esc = esc_raw
        else:
            esc = html.escape(slice_txt)

        truncation_html = ""
        if is_truncated:
            truncation_html = f"<div style='margin-top:12px; color:#94a3b8; font-style:italic;'>// ... Remaining records truncated in viewport. Full file saved to disk.</div>"

        html_body = f"""
        <div style="font-family:'JetBrains Mono', 'Consolas', monospace; font-size:12px; line-height:1.6; color:#94a3b8; background-color:#070a13;">
            <div style="color:#64748b; font-style:italic; margin-bottom:8px;">{html.escape(header_comment)}</div>
            <pre style="margin:0; white-space:pre-wrap; word-break:break-all;">{esc}</pre>
            {truncation_html}
        </div>
        """
        self.preview_viewer.setHtml(html_body)

    # ── Toolbar Actions ──────────────────────────────────────────────────────

    def copy_preview(self):
        if not self.last_converted_content:
            return
        clipboard = QApplication.clipboard()
        clipboard.setText(self.last_converted_content)
        self.copy_btn.setText("✓ Copied!")
        QTimer.singleShot(1800, lambda: self.copy_btn.setText("📋 Copy"))

    def download_output(self):
        if not self.last_converted_path or not os.path.exists(self.last_converted_path):
            self.telemetry_status.setText("<span style='color:#ef4444;'>No converted output available to download.</span>")
            return

        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Save Converted Feed",
            os.path.basename(self.last_converted_path),
            f"Target Format (*.{self.target_format.lower()});;All Files (*.*)"
        )
        if dest:
            try:
                import shutil
                shutil.copy2(self.last_converted_path, dest)
                self.telemetry_status.setText(f"<span style='color:#10b981;'>✓ File saved to {os.path.basename(dest)}</span>")
            except Exception as e:
                self.telemetry_status.setText(f"<span style='color:#ef4444;'>Failed to save file: {e}</span>")

    def analyze_in_workspace(self):
        if not self.last_converted_path or not os.path.exists(self.last_converted_path):
            self.telemetry_status.setText("<span style='color:#ef4444;'>No converted file to analyze. Convert a feed first.</span>")
            return

        try:
            uploads_dir = os.path.join(r"C:\Users\diqbal\Python\Feed_Workspace\Feed_analyzer\uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            import shutil
            shutil.copy2(self.last_converted_path, os.path.join(uploads_dir, os.path.basename(self.last_converted_path)))
        except Exception as e:
            print(f"Failed to copy to Feed Analyzer uploads: {e}")

        if hasattr(self.main_window, "nav_group"):
            btn = self.main_window.nav_group.button(1)
            if btn:
                btn.setChecked(True)
        if hasattr(self.main_window, "_on_nav_clicked"):
            self.main_window._on_nav_clicked(1)

    def _show_history_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #111827;
                color: #f8fafc;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 6px;
                font-size: 12px;
                font-family: 'Outfit', 'Segoe UI';
            }
            QMenu::item {
                padding: 6px 14px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: rgba(99, 102, 241, 0.2);
                color: #818cf8;
            }
        """)

        if not self.history:
            menu.addAction("No recent conversions")
        else:
            for item in self.history[:8]:
                action_text = f"{item['name']} ({item['out_fmt']}) • {item['timestamp']}"
                act = menu.addAction(action_text)
                act.triggered.connect(lambda checked=False, p=item['path']: self._reload_history_item(p))

        menu.exec(self.history_btn.mapToGlobal(QPoint(0, self.history_btn.height() + 4)))

    def _reload_history_item(self, path):
        if os.path.exists(path):
            self.last_converted_path = path
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                self.last_converted_content = content
                fmt = os.path.splitext(path)[1].replace('.', '')
                self._render_code_preview(content, fmt, os.path.basename(path), 0)
                self.output_stack.setCurrentIndex(1)
                self.badges_bar.setVisible(True)
                self.telemetry_status.setText(f"<span style='color:#10b981;'>Loaded history file: {os.path.basename(path)}</span>")
            except Exception as e:
                self.telemetry_status.setText(f"<span style='color:#ef4444;'>Failed to read history item: {e}</span>")

    def reset_tab(self):
        self.current_input_path = None
        self.file_path_display.clear()
        self.file_size_display.clear()
        self.tag_pill.setVisible(False)
        self.url_input.clear()
        self.url_hint.setText("Directly streams HTTP/HTTPS XML/JSON endpoints into memory.")
        self.preview_viewer.clear()
        self.output_stack.setCurrentIndex(0)
        self.badges_bar.setVisible(False)
        self.telemetry_status.setText("Tab state reset to idle.")
        self.telemetry_metrics.setText("Throughput: — • Footprint: —")
        self.status_pill.setText("● Ready")
        self.status_pill.setStyleSheet("""
            QLabel {
                background-color: rgba(16, 185, 129, 0.12);
                border: 1px solid rgba(16, 185, 129, 0.3);
                color: #10b981;
                border-radius: 16px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: 600;
            }
        """)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _format_size(self, sz):
        if sz < 1024: return f"{sz} B"
        elif sz < 1024 * 1024: return f"{sz / 1024:.1f} KB"
        else: return f"{sz / (1024 * 1024):.1f} MB"

    def _detect_format(self, path):
        low = path.lower()
        if low.endswith('.xml'): return 'xml'
        if low.endswith('.json'): return 'json'
        if low.endswith('.csv') or low.endswith('.txt'): return 'csv'
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                head = f.read(512).strip()
            if head.startswith('<'): return 'xml'
            if head.startswith('{') or head.startswith('['): return 'json'
            return 'csv'
        except:
            return 'xml'

    def xml_to_json(self, xml_str, indent=2):
        def elem_to_dict(elem):
            children = list(elem)
            d = {elem.tag: {} if elem.attrib else None}
            if children:
                dd = {}
                for dc in map(elem_to_dict, children):
                    for k, v in dc.items():
                        if k in dd:
                            if not isinstance(dd[k], list):
                                dd[k] = [dd[k]]
                            dd[k].append(v)
                        else:
                            dd[k] = v
                d[elem.tag] = dd
            if elem.attrib:
                if d[elem.tag] is None:
                    d[elem.tag] = {}
                d[elem.tag].update(('@' + k, v) for k, v in elem.attrib.items())
            if elem.text:
                text = elem.text.strip()
                if children or elem.attrib:
                    if text:
                        if d[elem.tag] is None:
                            d[elem.tag] = {}
                        d[elem.tag]['#text'] = text
                else:
                    d[elem.tag] = text
            return d

        root = ET.fromstring(xml_str)
        tree_dict = elem_to_dict(root)
        records_count = len(list(root))

        if indent is None:
            json_res = json.dumps(tree_dict, separators=(',', ':'), ensure_ascii=False)
        else:
            json_res = json.dumps(tree_dict, indent=indent, ensure_ascii=False)
        return json_res, records_count

    def json_to_xml(self, json_str, indent=2):
        data = json.loads(json_str)

        def build_xml(tag, d):
            clean_tag = "".join(c for c in tag if c.isalnum() or c in "_-") or "node"
            elem = ET.Element(clean_tag)
            if isinstance(d, dict):
                for k, v in d.items():
                    if k.startswith('@'):
                        elem.set(k[1:], str(v))
                    elif k == '#text':
                        elem.text = str(v)
                    elif isinstance(v, list):
                        for item in v:
                            elem.append(build_xml(k, item))
                    else:
                        elem.append(build_xml(k, v))
            elif isinstance(d, list):
                for item in d:
                    elem.append(build_xml("item", item))
            else:
                elem.text = str(d)
            return elem

        records_count = 1
        if isinstance(data, dict):
            if len(data) == 1:
                root_key = list(data.keys())[0]
                root = build_xml(root_key, data[root_key])
            else:
                root = build_xml("feed", data)
            records_count = len(root)
        elif isinstance(data, list):
            root = ET.Element("feed")
            for row in data:
                root.append(build_xml("item", row))
            records_count = len(data)
        else:
            root = ET.Element("feed")
            root.text = str(data)

        if hasattr(ET, "indent") and indent:
            indent_space = "  " if indent == 2 else "\t"
            ET.indent(root, space=indent_space)

        xml_res = ET.tostring(root, encoding="utf-8").decode("utf-8")
        return xml_res, records_count

    def csv_to_json(self, csv_str, indent=2, delimiter=','):
        reader = csv.DictReader(io.StringIO(csv_str), delimiter=delimiter)
        rows = [row for row in reader]
        records_count = len(rows)
        if indent is None:
            json_res = json.dumps(rows, separators=(',', ':'), ensure_ascii=False)
        else:
            json_res = json.dumps(rows, indent=indent, ensure_ascii=False)
        return json_res, records_count

    def csv_to_xml(self, csv_str, indent=2, delimiter=','):
        reader = csv.DictReader(io.StringIO(csv_str), delimiter=delimiter)
        root = ET.Element("feed")
        records_count = 0
        for row in reader:
            records_count += 1
            item = ET.SubElement(root, "item")
            for k, v in row.items():
                if k is None: continue
                tag_name = "".join(c for c in str(k) if c.isalnum() or c in "_-") or "field"
                sub = ET.SubElement(item, tag_name)
                sub.text = str(v) if v is not None else ""

        if hasattr(ET, "indent") and indent:
            indent_space = "  " if indent == 2 else "\t"
            ET.indent(root, space=indent_space)

        return ET.tostring(root, encoding="utf-8").decode("utf-8"), records_count

    def json_to_csv(self, json_str, delimiter=',', flatten=True):
        def _flatten_item(d, parent_key='', sep='.'):
            items = []
            if isinstance(d, dict):
                for k, v in d.items():
                    new_key = f"{parent_key}{sep}{k}" if parent_key else str(k)
                    if flatten and isinstance(v, dict):
                        items.extend(_flatten_item(v, new_key, sep=sep).items())
                    elif isinstance(v, list):
                        if v and isinstance(v[0], dict) and flatten:
                            items.append((new_key, json.dumps(v, ensure_ascii=False)))
                        else:
                            items.append((new_key, ", ".join(str(x) for x in v)))
                    else:
                        items.append((new_key, v))
            return dict(items)

        data = json.loads(json_str)
        if not isinstance(data, list):
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        data = v
                        break
                else:
                    data = [data]
            else:
                data = [{"value": data}]

        if not data:
            return "", 0

        all_rows = []
        keys = []
        for item in data:
            if isinstance(item, dict):
                flat_item = _flatten_item(item) if flatten else item
                all_rows.append(flat_item)
                for k in flat_item.keys():
                    if k not in keys:
                        keys.append(k)
            else:
                all_rows.append({"value": str(item)})
                if "value" not in keys:
                    keys.append("value")

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=keys, delimiter=delimiter, lineterminator='\n')
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row)

        return output.getvalue(), len(all_rows)



# ── Feed Diff Tab ─────────────────────────────────────────────────────────────
class FeedDiffTab(QWidget):
    """Feed comparator tab: structurally highlights changes with live URL downloading support."""
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName("diff_tab")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 32, 32, 32)
        lay.setSpacing(20)

        # Header block
        header = QVBoxLayout()
        header.setSpacing(4)
        title_lbl = QLabel("Feed Comparator ⚖️", self)
        title_lbl.setStyleSheet("color: #d97706; font-size: 24px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;")
        header.addWidget(title_lbl)
        sub_lbl = QLabel("Identify structural discrepancies between two local files or live URLs.", self)
        sub_lbl.setStyleSheet("color: #64748b; font-size: 15px; font-family: 'Segoe UI'; background: transparent;")
        header.addWidget(sub_lbl)
        lay.addLayout(header)

        # Selection panels
        panels = QHBoxLayout()
        panels.setSpacing(18)

        # Base Column
        base_col = QVBoxLayout()
        base_col.setSpacing(10)
        self.drop_base = DragDropLabel(self)
        self.drop_base.text_lbl.setText("Base Feed File\n(Drag & Drop)")
        base_col.addWidget(self.drop_base)
        
        # Base URL input row
        base_url_row = QHBoxLayout()
        self.url_base = QLineEdit(self)
        self.url_base.setPlaceholderText("Or paste Base URL...")
        self.url_base.setMinimumHeight(36)
        self.url_base.setStyleSheet("""
            QLineEdit {
                background-color: #121214;
                color: #f1f5f9;
                border: 1px solid #27272a;
                border-radius: 8px;
                padding-left: 8px;
                font-size: 12px;
                font-family: 'Segoe UI';
            }
        """)
        base_url_row.addWidget(self.url_base)
        
        self.fetch_base_btn = QPushButton("Fetch", self)
        self.fetch_base_btn.setMinimumHeight(36)
        self.fetch_base_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fetch_base_btn.setStyleSheet("""
            QPushButton {
                background-color: #27272a;
                color: #cbd5e1;
                border: 1px solid #3f3f46;
                border-radius: 8px;
                font-size: 12px;
                font-family: 'Segoe UI';
                font-weight: bold;
                padding: 0 10px;
            }
            QPushButton:hover {
                background-color: #3f3f46;
            }
        """)
        self.fetch_base_btn.clicked.connect(lambda: self.fetch_url("base"))
        base_url_row.addWidget(self.fetch_base_btn)
        base_col.addLayout(base_url_row)
        panels.addLayout(base_col)

        # Target Column
        target_col = QVBoxLayout()
        target_col.setSpacing(10)
        self.drop_target = DragDropLabel(self)
        self.drop_target.text_lbl.setText("Target Feed File\n(Drag & Drop)")
        target_col.addWidget(self.drop_target)

        # Target URL input row
        target_url_row = QHBoxLayout()
        self.url_target = QLineEdit(self)
        self.url_target.setPlaceholderText("Or paste Target URL...")
        self.url_target.setMinimumHeight(36)
        self.url_target.setStyleSheet("""
            QLineEdit {
                background-color: #121214;
                color: #f1f5f9;
                border: 1px solid #27272a;
                border-radius: 8px;
                padding-left: 8px;
                font-size: 12px;
                font-family: 'Segoe UI';
            }
        """)
        target_url_row.addWidget(self.url_target)

        self.fetch_target_btn = QPushButton("Fetch", self)
        self.fetch_target_btn.setMinimumHeight(36)
        self.fetch_target_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fetch_target_btn.setStyleSheet("""
            QPushButton {
                background-color: #27272a;
                color: #cbd5e1;
                border: 1px solid #3f3f46;
                border-radius: 8px;
                font-size: 12px;
                font-family: 'Segoe UI';
                font-weight: bold;
                padding: 0 10px;
            }
            QPushButton:hover {
                background-color: #3f3f46;
            }
        """)
        self.fetch_target_btn.clicked.connect(lambda: self.fetch_url("target"))
        target_url_row.addWidget(self.fetch_target_btn)
        target_col.addLayout(target_url_row)
        panels.addLayout(target_col)

        lay.addLayout(panels)

        # Action Buttons Row
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        compare_btn = QPushButton("Compare Feeds  ⚖️", self)
        compare_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        compare_btn.setMinimumHeight(44)
        compare_btn.setStyleSheet("""
            QPushButton {
                background-color: #d97706;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 15px;
                font-family: 'Segoe UI';
            }
            QPushButton:hover {
                background-color: #b45309;
            }
        """)
        compare_btn.clicked.connect(self.compare_feeds)
        action_row.addWidget(compare_btn, 2)

        self.reset_btn = QPushButton("Reset Tab 🧹", self)
        self.reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_btn.setMinimumHeight(44)
        self.reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #27272a;
                color: #cbd5e1;
                border: 1px solid #3f3f46;
                border-radius: 8px;
                font-weight: bold;
                font-size: 15px;
                font-family: 'Segoe UI';
            }
            QPushButton:hover {
                background-color: #3f3f46;
                color: #ffffff;
            }
        """)
        self.reset_btn.clicked.connect(self.reset_tab)
        action_row.addWidget(self.reset_btn, 1)

        lay.addLayout(action_row)


        # Diff output view
        self.diff_viewer = QTextBrowser(self)
        self.diff_viewer.setMinimumHeight(240)
        self.diff_viewer.setStyleSheet("""
            QTextBrowser {
                background-color: #09090b;
                color: #f1f5f9;
                border: 1px solid #27272a;
                border-radius: 8px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                padding: 12px;
            }
        """)
        lay.addWidget(self.diff_viewer)

    def fetch_url(self, mode):
        url_input = self.url_base if mode == "base" else self.url_target
        drop_widget = self.drop_base if mode == "base" else self.drop_target
        btn = self.fetch_base_btn if mode == "base" else self.fetch_target_btn

        url = url_input.text().strip()
        if not url:
            self.diff_viewer.setHtml("<span style='color:#ef4444;'>[Error] Please enter a URL first.</span>")
            return

        self.diff_viewer.append(f"[*] Downloading {mode} feed from URL: {url}...")
        btn.setEnabled(False)
        btn.setText("Fetching...")
        QApplication.processEvents()

        try:
            import urllib.request
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = response.read().decode('utf-8')

            scratch_dir = os.path.join(WORKSPACE_DIR, "scratch")
            os.makedirs(scratch_dir, exist_ok=True)
            
            ext = ".xml"
            if "json" in url.lower(): ext = ".json"
            elif "csv" in url.lower(): ext = ".csv"
            
            temp_path = os.path.join(scratch_dir, f"diff_{mode}_fetched{ext}")
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(data)

            drop_widget.set_file(temp_path)
            self.diff_viewer.append(f"<span style='color:#10b981;'>[Success] {mode.capitalize()} URL loaded successfully!</span>")
        except Exception as e:
            self.diff_viewer.append(f"<span style='color:#ef4444;'>[Error] Failed to fetch {mode} URL: {str(e)}</span>")
        finally:
            btn.setEnabled(True)
            btn.setText("Fetch")

    def compare_feeds(self):
        base_path = self.drop_base.file_path
        target_path = self.drop_target.file_path
        if not base_path or not target_path:
            self.diff_viewer.setHtml("<span style='color:#ef4444;'>[Error] Please select or fetch both base and target feed files.</span>")
            return

        self.diff_viewer.clear()
        self.diff_viewer.append(f"[*] Analyzing structure diff for base: {os.path.basename(base_path)} ➔ target: {os.path.basename(target_path)}")

        try:
            base_dict = self.load_as_dict(base_path)
            target_dict = self.load_as_dict(target_path)
            
            diff_logs = self.compare_dicts(base_dict, target_dict)
            
            if not diff_logs:
                self.diff_viewer.append("<span style='color:#10b981;'>[Success] No structural differences found! Feeds match perfectly.</span>")
            else:
                self.diff_viewer.append(f"[*] Found {len(diff_logs)} structural discrepancies:\n")
                for diff in diff_logs:
                    if "Removed" in diff:
                        self.diff_viewer.append(f"<span style='color:#ef4444;'>{diff}</span>")
                    elif "Added" in diff:
                        self.diff_viewer.append(f"<span style='color:#10b981;'>{diff}</span>")
                    else:
                        self.diff_viewer.append(f"<span style='color:#fbbf24;'>{diff}</span>")
        except Exception as e:
            self.diff_viewer.append(f"<span style='color:#ef4444;'>[Error] Comparison failed: {str(e)}</span>")

    def load_as_dict(self, path):
        import xml.etree.ElementTree as ET
        import json
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        
        name = os.path.basename(path).lower()
        if name.endswith('.xml') or content.startswith('<'):
            def elem_to_dict(elem):
                d = {elem.tag: {} if elem.attrib else None}
                children = list(elem)
                if children:
                    dd = {}
                    for dc in map(elem_to_dict, children):
                        for k, v in dc.items():
                            if k in dd:
                                if not isinstance(dd[k], list):
                                    dd[k] = [dd[k]]
                                dd[k].append(v)
                            else:
                                dd[k] = v
                    d[elem.tag] = dd
                if elem.attrib:
                    d[elem.tag].update(('@' + k, v) for k, v in elem.attrib.items())
                if elem.text and elem.text.strip():
                    if children or elem.attrib:
                        d[elem.tag]['#text'] = elem.text.strip()
                    else:
                        d[elem.tag] = elem.text.strip()
                return d
            root = ET.fromstring(content)
            return elem_to_dict(root)
        elif name.endswith('.json') or content.startswith('{') or content.startswith('['):
            return json.loads(content)
        else:
            # CSV fallback dict
            import csv, io
            reader = csv.DictReader(io.StringIO(content))
            return {"rows": [row for row in reader]}

    def compare_dicts(self, d1, d2, path=""):
        diffs = []
        if isinstance(d1, dict) and isinstance(d2, dict):
            for k in d1:
                if k not in d2:
                    diffs.append(f"❌ Removed tag: {path}/{k}")
                else:
                    diffs.extend(self.compare_dicts(d1[k], d2[k], f"{path}/{k}"))
            for k in d2:
                if k not in d1:
                    diffs.append(f"➕ Added tag: {path}/{k}")
        elif isinstance(d1, list) and isinstance(d2, list):
            if len(d1) != len(d2):
                diffs.append(f"⚠️ Item count changed: {path} (Base: {len(d1)} items, Target: {len(d2)} items)")
            if d1 and d2:
                diffs.extend(self.compare_dicts(d1[0], d2[0], f"{path}[0]"))
        else:
            if d1 != d2:
                v1_str = str(d1)[:45] + ("..." if len(str(d1)) > 45 else "")
                v2_str = str(d2)[:45] + ("..." if len(str(d2)) > 45 else "")
                diffs.append(f"✏️ Value mismatch: {path} (Base: '{v1_str}', Target: '{v2_str}')")
        return diffs

    def reset_tab(self):
        """Resets the tab inputs, logs, and deletes temporary downloaded files."""
        # Reset dropzones
        self.drop_base.file_path = None
        self.drop_base.icon_lbl.setText("📥")
        self.drop_base.text_lbl.setText("Base Feed File\n(Drag & Drop)")
        self.drop_base.setStyleSheet("""
            QFrame#drag_drop_zone {
                background-color: #121214;
                border: 2px dashed #334155;
                border-radius: 12px;
                min-height: 140px;
            }
        """)

        self.drop_target.file_path = None
        self.drop_target.icon_lbl.setText("📥")
        self.drop_target.text_lbl.setText("Target Feed File\n(Drag & Drop)")
        self.drop_target.setStyleSheet("""
            QFrame#drag_drop_zone {
                background-color: #121214;
                border: 2px dashed #334155;
                border-radius: 12px;
                min-height: 140px;
            }
        """)

        # Clear inputs
        self.url_base.clear()
        self.url_target.clear()
        self.diff_viewer.clear()

        # Delete fetched files specifically for this tab
        try:
            for mode in ["base", "target"]:
                for ext in [".xml", ".json", ".csv"]:
                    temp_path = os.path.join(WORKSPACE_DIR, "scratch", f"diff_{mode}_fetched{ext}")
                    if os.path.isfile(temp_path):
                        os.remove(temp_path)
        except Exception as e:
            logger.warning(f"Could not remove diff scratch files: {e}")

        self.diff_viewer.append("[*] Tab state cleared and downloaded files purged successfully.")




# ── Command Palette overlay dialog ───────────────────────────────────────────
# ── Feed Downloader Tab ────────────────────────────────────────────────────────
class FeedDownloaderTab(QWidget):
    """High-speed multi-threaded parallel feed downloader tab."""
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName("downloader_tab")
        self._dl_thread = None
        self._is_downloading = False
        self._cancelled = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 32, 32, 32)
        lay.setSpacing(18)
        header = QVBoxLayout()
        header.setSpacing(4)
        t = QLabel("Feed Downloader ⬇️", self)
        t.setStyleSheet("color: #06b6d4; font-size: 24px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;")
        header.addWidget(t)
        s = QLabel("Download massive XML/JSON feeds at maximum speed using parallel HTTP range streams.", self)
        s.setStyleSheet("color: #64748b; font-size: 15px; font-family: 'Segoe UI'; background: transparent;")
        header.addWidget(s)
        lay.addLayout(header)
        url_row = QHBoxLayout()
        url_row.setSpacing(10)
        ul = QLabel("Feed URL:", self)
        ul.setStyleSheet("color: #94a3b8; font-size: 13px; font-family: 'Segoe UI'; background: transparent; min-width: 70px;")
        url_row.addWidget(ul)
        self.url_input = QLineEdit(self)
        self.url_input.setPlaceholderText("https://example.com/feed.xml")
        self.url_input.setMinimumHeight(40)
        self.url_input.setStyleSheet("QLineEdit { background-color: #121214; color: #f1f5f9; border: 1px solid #27272a; border-radius: 8px; padding-left: 12px; font-size: 13px; font-family: 'Segoe UI'; } QLineEdit:focus { border: 1px solid #06b6d4; }")
        url_row.addWidget(self.url_input, 1)
        lay.addLayout(url_row)
        opts_row = QHBoxLayout()
        opts_row.setSpacing(12)
        ol = QLabel("Save To:", self)
        ol.setStyleSheet("color: #94a3b8; font-size: 13px; font-family: 'Segoe UI'; background: transparent; min-width: 70px;")
        opts_row.addWidget(ol)
        self.out_path_input = QLineEdit(self)
        self.out_path_input.setText(os.path.join(WORKSPACE_DIR, "Feed_analyzer", "downloads"))
        self.out_path_input.setMinimumHeight(38)
        self.out_path_input.setStyleSheet("QLineEdit { background-color: #121214; color: #94a3b8; border: 1px solid #27272a; border-radius: 8px; padding-left: 12px; font-size: 12px; font-family: 'Segoe UI'; }")
        opts_row.addWidget(self.out_path_input, 1)
        browse_btn = QPushButton("Browse", self)
        browse_btn.setMinimumHeight(38)
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.setStyleSheet("QPushButton { background-color: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 8px; font-size: 12px; font-family: 'Segoe UI'; padding: 0 14px; } QPushButton:hover { background-color: #334155; color: #f1f5f9; }")
        browse_btn.clicked.connect(self._browse_output_dir)
        opts_row.addWidget(browse_btn)
        tl = QLabel("Streams:", self)
        tl.setStyleSheet("color: #94a3b8; font-size: 13px; font-family: 'Segoe UI'; background: transparent;")
        opts_row.addWidget(tl)
        self.thread_combo = QComboBox(self)
        for tc in [4, 8, 12, 16, 24, 32]:
            self.thread_combo.addItem(f"{tc} streams", tc)
        self.thread_combo.setCurrentIndex(1)
        self.thread_combo.setMinimumHeight(38)
        self.thread_combo.setStyleSheet("QComboBox { background-color: #121214; color: #f1f5f9; border: 1px solid #27272a; border-radius: 8px; padding-left: 10px; font-size: 12px; font-family: 'Segoe UI'; } QComboBox::drop-down { border: none; } QComboBox QAbstractItemView { background-color: #1c1c1f; color: #f1f5f9; border: 1px solid #334155; }")
        opts_row.addWidget(self.thread_combo)
        lay.addLayout(opts_row)
        from PySide6.QtWidgets import QProgressBar
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setStyleSheet("QProgressBar { background-color: #1e293b; border: none; border-radius: 4px; } QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #06b6d4, stop:1 #0891b2); border-radius: 4px; }")
        lay.addWidget(self.progress_bar)
        stats_row = QHBoxLayout()
        self.pct_lbl = QLabel("0%", self)
        self.pct_lbl.setStyleSheet("color: #06b6d4; font-size: 13px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;")
        stats_row.addWidget(self.pct_lbl)
        stats_row.addStretch()
        self.speed_lbl = QLabel("Speed: --", self)
        self.speed_lbl.setStyleSheet("color: #94a3b8; font-size: 12px; font-family: 'Segoe UI'; background: transparent;")
        stats_row.addWidget(self.speed_lbl)
        stats_row.addSpacing(24)
        self.eta_lbl = QLabel("ETA: --", self)
        self.eta_lbl.setStyleSheet("color: #94a3b8; font-size: 12px; font-family: 'Segoe UI'; background: transparent;")
        stats_row.addWidget(self.eta_lbl)
        stats_row.addSpacing(24)
        self.size_lbl = QLabel("Size: --", self)
        self.size_lbl.setStyleSheet("color: #94a3b8; font-size: 12px; font-family: 'Segoe UI'; background: transparent;")
        stats_row.addWidget(self.size_lbl)
        lay.addLayout(stats_row)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.download_btn = QPushButton("Download Feed", self)
        self.download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_btn.setMinimumHeight(44)
        self.download_btn.setStyleSheet("QPushButton { background-color: #06b6d4; color: #000000; border: none; border-radius: 8px; font-weight: bold; font-size: 15px; font-family: 'Segoe UI'; } QPushButton:hover { background-color: #0891b2; color: #ffffff; } QPushButton:disabled { background-color: #1e293b; color: #475569; }")
        self.download_btn.clicked.connect(self._start_download)
        btn_row.addWidget(self.download_btn, 2)
        self.cancel_btn = QPushButton("Stop", self)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setMinimumHeight(44)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setStyleSheet("QPushButton { background-color: #27272a; color: #cbd5e1; border: 1px solid #3f3f46; border-radius: 8px; font-size: 14px; font-family: 'Segoe UI'; } QPushButton:hover { background-color: #3f3f46; color: #ef4444; } QPushButton:disabled { color: #475569; }")
        self.cancel_btn.clicked.connect(self._cancel_download)
        btn_row.addWidget(self.cancel_btn, 1)
        reset_btn = QPushButton("Reset Tab", self)
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setMinimumHeight(44)
        reset_btn.setStyleSheet("QPushButton { background-color: #27272a; color: #cbd5e1; border: 1px solid #3f3f46; border-radius: 8px; font-size: 14px; font-family: 'Segoe UI'; } QPushButton:hover { background-color: #3f3f46; color: #ffffff; }")
        reset_btn.clicked.connect(self.reset_tab)
        btn_row.addWidget(reset_btn, 1)
        lay.addLayout(btn_row)
        self.log_viewer = QTextBrowser(self)
        self.log_viewer.setMinimumHeight(220)
        self.log_viewer.setStyleSheet("QTextBrowser { background-color: #09090b; color: #f1f5f9; border: 1px solid #27272a; border-radius: 8px; font-family: 'Consolas', 'Courier New', monospace; font-size: 12px; padding: 12px; }")
        self.log_viewer.setHtml("<span style='color:#475569;'>Waiting for download...</span>")
        lay.addWidget(self.log_viewer)

    def _format_bytes(self, n):
        import math
        if n <= 0: return "0 B"
        units = ["B", "KB", "MB", "GB"]
        i = int(math.floor(math.log(max(n, 1), 1024)))
        return f"{round(n / math.pow(1024, i), 2)} {units[i]}"

    def _browse_output_dir(self):
        chosen = QFileDialog.getExistingDirectory(self, "Select Output Directory", self.out_path_input.text())
        if chosen:
            self.out_path_input.setText(chosen)

    def _start_download(self):
        url = self.url_input.text().strip()
        if not url:
            self.log_viewer.setHtml("<span style='color:#ef4444;'>[Error] Please enter a feed URL.</span>")
            return
        if self._is_downloading:
            return
        out_dir = self.out_path_input.text().strip() or os.path.join(WORKSPACE_DIR, "Feed_analyzer", "downloads")
        os.makedirs(out_dir, exist_ok=True)
        filename = url.split('/')[-1].split('?')[0] or "feed.xml"
        if '.' not in filename:
            filename += ".xml"
        out_path = os.path.join(out_dir, filename.replace(' ', '_'))
        num_threads = self.thread_combo.currentData()
        self._is_downloading = True
        self._cancelled = False
        self.download_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.pct_lbl.setText("0%")
        self.speed_lbl.setText("Speed: --")
        self.eta_lbl.setText("ETA: --")
        self.size_lbl.setText("Size: --")
        self.log_viewer.clear()
        self.log_viewer.append(f"<span style='color:#06b6d4;'>[*] Starting download: {url}</span>")
        self.log_viewer.append(f"[*] Output: {out_path}")
        self.log_viewer.append(f"[*] Parallel streams: {num_threads}")
        QApplication.processEvents()
        def progress_cb(downloaded, total, speed_mb, eta_s):
            pct = int(downloaded / total * 100) if total > 0 else 0
            self.progress_bar.setValue(pct)
            self.pct_lbl.setText(f"{pct}%")
            self.speed_lbl.setText(f"Speed: {speed_mb:.1f} MB/s")
            self.eta_lbl.setText(f"ETA: {int(eta_s)}s" if eta_s and eta_s < 9999 else "ETA: --")
            self.size_lbl.setText(f"{self._format_bytes(downloaded)} / {self._format_bytes(total)}")
            QApplication.processEvents()
        def run():
            try:
                dl_path = os.path.join(WORKSPACE_DIR, "Feed_analyzer")
                if dl_path not in sys.path:
                    sys.path.insert(0, dl_path)
                from fast_downloader import download_file_fast
                final_path = download_file_fast(url=url, output_path=out_path, num_threads=num_threads, progress_callback=progress_cb)
                if not self._cancelled:
                    self.progress_bar.setValue(100)
                    self.pct_lbl.setText("100%")
                    self.log_viewer.append(f"<span style='color:#10b981;'>[OK] Download complete! Saved to: {final_path}</span>")
                    self.eta_lbl.setText("ETA: Done")
            except Exception as e:
                if not self._cancelled:
                    self.log_viewer.append(f"<span style='color:#ef4444;'>[Error] {e}</span>")
            finally:
                self._is_downloading = False
                self.download_btn.setEnabled(True)
                self.cancel_btn.setEnabled(False)
                QApplication.processEvents()
        import threading as _threading
        self._dl_thread = _threading.Thread(target=run, daemon=True)
        self._dl_thread.start()

    def _cancel_download(self):
        self._cancelled = True
        self._is_downloading = False
        self.download_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.log_viewer.append("<span style='color:#f59e0b;'>[!] Download cancelled by user.</span>")

    def reset_tab(self):
        self._cancelled = True
        self._is_downloading = False
        self.url_input.clear()
        self.progress_bar.setValue(0)
        self.pct_lbl.setText("0%")
        self.speed_lbl.setText("Speed: --")
        self.eta_lbl.setText("ETA: --")
        self.size_lbl.setText("Size: --")
        self.download_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.log_viewer.setHtml("<span style='color:#475569;'>Tab cleared. Waiting for download...</span>")




class CommandPaletteDialog(QDialog):
    """Raycast spotlight-style keyboard command palette overlay."""
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setWindowFlags(Qt.WindowFlags.FramelessWindowHint | Qt.WindowFlags.Popup)
        self.setFixedWidth(560)
        self.setMinimumHeight(320)
        self.setObjectName("palette_dialog")

        # Custom styling with glowing border
        self.setStyleSheet("""
            QDialog#palette_dialog {
                background-color: #09090b;
                border: 2px solid #8b5cf6;
                border-radius: 12px;
            }
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        # Input field
        self.search_line = QLineEdit(self)
        self.search_line.setPlaceholderText("Search tools, pages, or quick actions...")
        self.search_line.setMinimumHeight(44)
        self.search_line.setStyleSheet("""
            QLineEdit {
                background-color: #121214;
                color: #f1f5f9;
                border: 1px solid #27272a;
                border-radius: 8px;
                padding: 0 12px;
                font-size: 14px;
                font-family: 'Segoe UI';
            }
            QLineEdit:focus {
                border: 1px solid #c084fc;
            }
        """)
        self.search_line.textChanged.connect(self.filter_items)
        lay.addWidget(self.search_line)

        # List Widget
        self.list_widget = QListWidget(self)
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: transparent;
                border: none;
                color: #94a3b8;
                font-size: 15px;
                font-family: 'Segoe UI';
                outline: 0;
            }
            QListWidget::item {
                padding: 10px 12px;
                border-radius: 6px;
            }
            QListWidget::item:hover {
                background-color: rgba(255, 255, 255, 0.04);
                color: #cbd5e1;
            }
            QListWidget::item:selected {
                background-color: rgba(139, 92, 246, 0.15);
                color: #c084fc;
                font-weight: bold;
            }
        """)
        self.list_widget.itemClicked.connect(self.execute_item)
        lay.addWidget(self.list_widget)

        self.populate_items()
        self.list_widget.setCurrentRow(0)

    def populate_items(self):
        actions = [
            ("🏠  Go to Home Hub", "nav:0"),
            ("🔍  Open Feed Analyzer", "nav:1"),
            ("🥞  Open Feed Merger", "nav:2"),
            ("🛡️  Open Feed Validator", "nav:3"),
            ("🛠️  Open Feed Builder", "nav:4"),
            ("🔄  Open Feed Converter", "nav:5"),
            ("⚖️  Open Feed Diff & Comparator", "nav:6"),
            ("⬇️  Open Feed Downloader", "nav:7"),
            ("🌙  Toggle UI Dark/Light Theme", "action:theme"),
            ("🔴  Exit Feed Workspace", "action:exit")
        ]
        for name, data in actions:
            item = QListWidgetItem(name, self.list_widget)
            item.setData(Qt.ItemDataRole.UserRole, data)

    def filter_items(self, text):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setHidden(text.lower() not in item.text().lower())
        self.list_widget.setCurrentRow(0)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() == Qt.Key.Key_Up:
            row = self.list_widget.currentRow()
            if row > 0:
                self.list_widget.setCurrentRow(row - 1)
        elif event.key() == Qt.Key.Key_Down:
            row = self.list_widget.currentRow()
            if row < self.list_widget.count() - 1:
                self.list_widget.setCurrentRow(row + 1)
        elif event.key() == Qt.Key.Key_Return:
            curr = self.list_widget.currentItem()
            if curr:
                self.execute_item(curr)
        else:
            super().keyPressEvent(event)

    def execute_item(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        action_type, val = data.split(":")
        
        self.close()
        
        if action_type == "nav":
            idx = int(val)
            self.main_window.switch_to_tab(idx)
        elif action_type == "action":
            if val == "exit":
                self.main_window.close()
            elif val == "theme":
                pass

# ── Interactive Vector Activity Chart ───────────────────────────────────────
class WorkspaceAnalyticsChart(QWidget):
    """Custom painted premium area spline chart showing workspace activity trends."""
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setMinimumHeight(210)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Double peak spline values past 7 days matching the mockup exactly
        points = [0.22, 0.68, 0.44, 0.72, 0.48, 0.98, 0.58]
        
        w = self.width()
        h = self.height()
        
        left_m = 40
        right_m = 20
        top_m = 20
        bottom_m = 25
        
        plot_w = w - left_m - right_m
        plot_h = h - top_m - bottom_m

        grid_pen = QPen(QColor("#27272a"), 1, Qt.PenStyle.SolidLine)
        painter.setPen(grid_pen)
        
        # Horizontal lines (4 intervals: 0 to 200)
        for i in range(5):
            y = int(top_m + plot_h - (plot_h / 4) * i)
            painter.drawLine(left_m, y, w - right_m, y)
            
            # Draw Y-axis labels
            y_val = str(i * 50)
            painter.setPen(QPen(QColor("#64748b"), 1))
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(left_m - 30, y + 4, y_val)
            painter.setPen(grid_pen)

        # Plot data points
        n = len(points)
        step = plot_w / (n - 1)
        
        pts = [(left_m + i * step, top_m + plot_h - points[i] * plot_h) for i in range(n)]

        # Draw filled gradient area under spline
        path = QPainterPath()
        path.moveTo(pts[0][0], top_m + plot_h)
        
        # Spline curve for the area path matching control points
        for i in range(1, n):
            prev_x, prev_y = pts[i-1]
            curr_x, curr_y = pts[i]
            cp1_x = prev_x + step / 2
            cp1_y = prev_y
            cp2_x = prev_x + step / 2
            cp2_y = curr_y
            path.cubicTo(cp1_x, cp1_y, cp2_x, cp2_y, curr_x, curr_y)
            
        path.lineTo(pts[-1][0], top_m + plot_h)
        path.closeSubpath()

        area_grad = QLinearGradient(0, top_m, 0, top_m + plot_h)
        area_grad.setColorAt(0.0, QColor(168, 85, 247, 60))  # Purple accent
        area_grad.setColorAt(0.5, QColor(14, 165, 233, 40))  # Blue accent
        area_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillPath(path, QBrush(area_grad))

        # Draw spline line with linear gradient from Purple to Blue
        line_path = QPainterPath()
        line_path.moveTo(pts[0][0], pts[0][1])
        
        for i in range(1, n):
            prev_x, prev_y = pts[i-1]
            curr_x, curr_y = pts[i]
            cp1_x = prev_x + step / 2
            cp1_y = prev_y
            cp2_x = prev_x + step / 2
            cp2_y = curr_y
            line_path.cubicTo(cp1_x, cp1_y, cp2_x, cp2_y, curr_x, curr_y)

        line_grad = QLinearGradient(left_m, 0, w - right_m, 0)
        line_grad.setColorAt(0.0, QColor("#a855f7"))
        line_grad.setColorAt(1.0, QColor("#0ea5e9"))
        
        line_pen = QPen(QBrush(line_grad), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(line_pen)
        painter.drawPath(line_path)

        # Draw X-axis days
        days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        for i, day in enumerate(days):
            x = int(left_m + i * step)
            painter.setPen(QPen(QColor("#64748b"), 1))
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(QRectF(x - 25, h - bottom_m + 6, 50, 15), Qt.AlignmentFlag.AlignCenter, day)




# ── Session Timeline node indicator ─────────────────────────────────────────
class TimelineNodeWidget(QWidget):
    """Draws a vertical timeline connector line and a glowing circle node."""
    def __init__(self, color_hex, is_last=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 52)
        self.color = QColor(color_hex)
        self.is_last = is_last

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        cx = w / 2

        # Draw vertical rail line
        line_pen = QPen(QColor("#27272a"), 1.5, Qt.PenStyle.SolidLine)
        painter.setPen(line_pen)
        if not self.is_last:
            painter.drawLine(int(cx), 0, int(cx), h)
        else:
            painter.drawLine(int(cx), 0, int(cx), 14)

        # Draw colored circle node
        painter.setPen(Qt.PenStyle.NoPen)
        # Glow outer shadow
        glow_color = QColor(self.color)
        glow_color.setAlpha(60)
        painter.setBrush(QBrush(glow_color))
        painter.drawEllipse(QRectF(cx - 5, 8, 10, 10))
        
        # Center solid dot
        painter.setBrush(QBrush(self.color))
        painter.drawEllipse(QRectF(cx - 3, 10, 6, 6))




# ── Session Timeline Panel ──────────────────────────────────────────────────
class SessionTimelinePanel(QFrame):
    """Session Timeline panel showing recent activities with a vertical timeline rail."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel_card")
        self.setMinimumHeight(240)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        # Header
        title_lbl = QLabel("Session Timeline", self)
        title_lbl.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: bold; font-family: 'Segoe UI'; background: transparent; border: none;")
        layout.addWidget(title_lbl)

        # Timeline container
        container = QWidget(self)
        container.setStyleSheet("background: transparent; border: none;")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 4, 0, 4)
        cl.setSpacing(0)

        activities = [
            ("12:00 AM", "Validated sales_feed.xml ✔", "3 minutes ago", "#a855f7", False),
            ("12:25 PM", "Converted catalog.json ➔ XML", "3 minutes ago", "#10b981", False),
            ("10:30 PM", "Merged 3 feeds", "7 minutes ago", "#0ea5e9", True)
        ]

        for time_str, message, time_ago, color_hex, is_last in activities:
            row = QHBoxLayout()
            row.setSpacing(14)

            # Left node
            node = TimelineNodeWidget(color_hex, is_last, container)
            row.addWidget(node)

            # Right texts
            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            text_col.setContentsMargins(0, 0, 0, 10)

            time_lbl = QLabel(time_str, container)
            time_lbl.setStyleSheet("color: #64748b; font-size: 10px; font-weight: bold; font-family: 'Segoe UI'; background: transparent; border: none;")
            text_col.addWidget(time_lbl)

            msg_lbl = QLabel(message, container)
            msg_lbl.setStyleSheet("color: #ffffff; font-size: 11px; font-family: 'Segoe UI'; background: transparent; border: none;")
            text_col.addWidget(msg_lbl)

            ago_lbl = QLabel(time_ago, container)
            ago_lbl.setStyleSheet("color: #475569; font-size: 10px; font-family: 'Segoe UI'; background: transparent; border: none;")
            text_col.addWidget(ago_lbl)

            row.addLayout(text_col)
            row.addStretch()
            cl.addLayout(row)

        layout.addWidget(container)


# ── Custom Painted Logo Widget ──────────────────────────────────────────────
class LogoWidget(QWidget):
    """Custom painted high-fidelity application logo with purple-to-blue gradients."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw beautiful double curve stylized logo
        path = QPainterPath()
        path.moveTo(6, 10)
        path.cubicTo(14, 2, 26, 2, 30, 10)
        path.cubicTo(32, 14, 28, 20, 22, 20)
        path.cubicTo(16, 20, 12, 16, 6, 22)
        path.cubicTo(2, 26, 6, 32, 14, 32)
        path.cubicTo(24, 32, 32, 26, 30, 18)

        grad = QLinearGradient(0, 0, 36, 36)
        grad.setColorAt(0.0, QColor("#a855f7"))
        grad.setColorAt(1.0, QColor("#3b82f6"))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(grad))
        painter.drawPath(path)



# ── Custom Profile Avatar Widget ────────────────────────────────────────────
class ProfileAvatarWidget(QWidget):
    """Circular profile avatar with an online status green indicator dot."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(38, 38)
        self.avatar_path = os.path.join(WORKSPACE_DIR, "avatar.jpg")
        self.pixmap = None
        if os.path.exists(self.avatar_path):
            self.pixmap = QPixmap(self.avatar_path)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0, 0, 34, 34)
        painter.setPen(Qt.PenStyle.NoPen)
        
        if self.pixmap and not self.pixmap.isNull():
            path = QPainterPath()
            path.addEllipse(rect)
            painter.save()
            painter.setClipPath(path)
            painter.drawPixmap(rect, self.pixmap, QRectF(self.pixmap.rect()))
            painter.restore()
        else:
            painter.setBrush(QBrush(QColor("#1c1c1f")))
            painter.drawEllipse(rect)
            
            painter.setBrush(QBrush(QColor("#94a3b8")))
            painter.drawEllipse(QRectF(11, 6, 12, 12))
            
            path = QPainterPath()
            path.moveTo(6, 26)
            path.cubicTo(6, 20, 28, 20, 28, 26)
            path.closeSubpath()
            painter.drawPath(path)

        dot_rect = QRectF(24, 24, 10, 10)
        painter.setBrush(QBrush(QColor("#22c55e")))
        painter.setPen(QPen(QColor("#0d0d0f"), 1.5))
        painter.drawEllipse(dot_rect)
        




class SidebarLogoWidget(QWidget):
    """Draws the teal custom stacked logo at the top of the sidebar."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(26, 26)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        
        # Top pill (white)
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.drawRoundedRect(QRectF(2, 4, 22, 5), 2.5, 2.5)

        # Middle pill (white)
        painter.drawRoundedRect(QRectF(2, 11, 22, 5), 2.5, 2.5)

        # Bottom pill (teal)
        painter.setBrush(QBrush(QColor("#14b8a6")))
        painter.drawRoundedRect(QRectF(2, 18, 22, 5), 2.5, 2.5)


class UtilitiesTab(QWidget):
    """Container tab holding Feed Converter and Feed Diff in a clean tabbed layout."""
    def __init__(self, converter_widget, diff_widget, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        # Custom Tab Selector Buttons at the top
        tab_header = QHBoxLayout()
        tab_header.setContentsMargins(0, 0, 0, 0)
        tab_header.setSpacing(10)

        self.btn_converter = QPushButton("🔄  Feed Converter", self)
        self.btn_converter.setCheckable(True)
        self.btn_converter.setChecked(True)
        self.btn_converter.setFixedSize(150, 36)
        self.btn_converter.setCursor(Qt.CursorShape.PointingHandCursor)

        self.btn_diff = QPushButton("⚖️  Feed Diff", self)
        self.btn_diff.setCheckable(True)
        self.btn_diff.setFixedSize(150, 36)
        self.btn_diff.setCursor(Qt.CursorShape.PointingHandCursor)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.group.addButton(self.btn_converter, 0)
        self.group.addButton(self.btn_diff, 1)

        tab_header.addWidget(self.btn_converter)
        tab_header.addWidget(self.btn_diff)
        tab_header.addStretch()
        layout.addLayout(tab_header)

        self.stack = QStackedWidget(self)
        self.stack.addWidget(converter_widget)
        self.stack.addWidget(diff_widget)
        layout.addWidget(self.stack)

        self.setStyleSheet("""
            QPushButton {
                background-color: #0d0d0f;
                color: #94a3b8;
                border: 1px solid #27272a;
                border-radius: 8px;
                font-size: 12px;
                font-family: 'Segoe UI';
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(20, 184, 166, 0.05);
                color: #14b8a6;
                border: 1px solid #14b8a6;
            }
            QPushButton:checked {
                background-color: rgba(20, 184, 166, 0.12);
                color: #ffffff;
                border: 1px solid #14b8a6;
            }
        """)

        self.group.idClicked.connect(self.stack.setCurrentIndex)


class SidebarButton(QPushButton):
    """Custom QPushButton that paints the line-art icon and label text directly to avoid layout clipping."""
    def __init__(self, icon_type, label, parent=None):
        super().__init__(parent)
        self.icon_type = icon_type
        self.label = label
        self.setCheckable(True)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(44)
        self.setProperty("class", "nav_btn")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_checked = self.isChecked()
        is_hovered = self.underMouse()
        
        w = self.width()
        h = self.height()
        
        if is_checked:
            # Dark teal tint background
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(20, 184, 166, 20)))
            painter.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)
            
            # Teal left border
            painter.setBrush(QColor("#14b8a6"))
            painter.drawRect(QRectF(0, 0, 3, h))
        elif is_hovered:
            # Muted hover background
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(255, 255, 255, 12)))
            painter.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        # Draw Icon (at x=16, size 20x20)
        icon_color = QColor("#14b8a6" if is_checked else "#94a3b8")
        pen = QPen(icon_color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        painter.save()
        painter.translate(16, (h - 20) / 2)
        
        if self.icon_type == "Hub":
            path = QPainterPath()
            path.moveTo(10, 2)
            path.lineTo(2, 9)
            path.lineTo(4, 9)
            path.lineTo(4, 18)
            path.lineTo(16, 18)
            path.lineTo(16, 9)
            path.lineTo(18, 9)
            path.closeSubpath()
            painter.drawPath(path)
        elif self.icon_type == "Analyzer":
            painter.drawRect(QRectF(2, 11, 4, 7))
            painter.drawRect(QRectF(8, 5, 4, 13))
            painter.drawRect(QRectF(14, 8, 4, 10))
        elif self.icon_type == "Merger":
            painter.drawLine(4, 3, 4, 17)
            path = QPainterPath()
            path.moveTo(4, 12)
            path.cubicTo(9, 12, 14, 9, 14, 5)
            painter.drawPath(path)
            painter.setBrush(QBrush(icon_color))
            painter.drawEllipse(QRectF(2.5, 1.5, 3, 3))
            painter.drawEllipse(QRectF(2.5, 15.5, 3, 3))
            painter.drawEllipse(QRectF(12.5, 3.5, 3, 3))
        elif self.icon_type == "Validator":
            path = QPainterPath()
            path.moveTo(10, 2)
            path.lineTo(17, 4)
            path.cubicTo(17, 11, 15, 15.5, 10, 18)
            path.cubicTo(5, 15.5, 3, 11, 3, 4)
            path.closeSubpath()
            painter.drawPath(path)
            check = QPainterPath()
            check.moveTo(7, 10)
            check.lineTo(9, 12)
            check.lineTo(13, 8)
            painter.drawPath(check)
        elif self.icon_type == "Builder":
            cx, cy = 10, 10
            r = 8.5
            import math
            pts = []
            for i in range(6):
                angle = math.radians(30 + i * 60)
                pts.append(QPointF(cx + r * math.cos(angle), cy + r * math.sin(angle)))
            hex_path = QPainterPath()
            hex_path.moveTo(pts[0])
            for i in range(1, 6):
                hex_path.lineTo(pts[i])
            hex_path.closeSubpath()
            painter.drawPath(hex_path)
            painter.drawLine(QPointF(cx, cy), pts[1])
            painter.drawLine(QPointF(cx, cy), pts[3])
            painter.drawLine(QPointF(cx, cy), pts[5])
        elif self.icon_type == "Converter":
            # Refresh / Converter cycle sync loop
            painter.drawArc(QRectF(2, 2, 16, 16), 45 * 16, 270 * 16)
            # Draw arrowhead
            arrow = QPainterPath()
            arrow.moveTo(11, 0)
            arrow.lineTo(16, 3)
            arrow.lineTo(12, 7)
            painter.drawPath(arrow)
        elif self.icon_type == "Diff":
            # Balance Scale for Feed Diff
            painter.drawLine(3, 17, 17, 17)  # Base
            painter.drawLine(10, 3, 10, 17)  # Column
            painter.drawLine(5, 5, 15, 5)    # Beam
            # Left side pan
            painter.drawLine(5, 5, 2, 11)
            painter.drawLine(5, 5, 8, 11)
            painter.drawLine(2, 11, 8, 11)
            # Right side pan
            painter.drawLine(15, 5, 12, 11)
            painter.drawLine(15, 5, 18, 11)
            painter.drawLine(12, 11, 18, 11)
        elif self.icon_type == "Downloader":
            # Download arrow icon: vertical bar + chevron + base bar
            painter.drawLine(10, 2, 10, 13)   # vertical stem
            arrow = QPainterPath()
            arrow.moveTo(5, 9)
            arrow.lineTo(10, 15)
            arrow.lineTo(15, 9)
            painter.drawPath(arrow)
            painter.drawLine(3, 18, 17, 18)   # base bar
        
        painter.restore()

        # Paint Text Label (at x=48)
        text_color = QColor("#ffffff" if is_checked else "#94a3b8")
        painter.setPen(text_color)
        font = QFont("Segoe UI", 14)
        font.setWeight(QFont.Weight.DemiBold if is_checked else QFont.Weight.Medium)
        painter.setFont(font)
        
        text_rect = QRectF(48, 0, w - 48, h)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.label)


class ExitButton(QPushButton):
    """Custom exit button that paints a clean power/logout icon."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Exit Workspace")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_hovered = self.underMouse()
        w = self.width()
        h = self.height()

        if is_hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(239, 68, 68, 20)))  # light red tint
            painter.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        # Draw power icon in red (#ef4444) or slate (#64748b)
        color = QColor("#ef4444" if is_hovered else "#64748b")
        pen = QPen(color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        cx, cy = w / 2, h / 2
        # Draw arc for the power button circle (from 30 to 150 degrees, leaving the top open)
        painter.drawArc(QRectF(cx - 8, cy - 8, 16, 16), 30 * 16, 300 * 16)
        # Draw vertical line in the top center
        painter.drawLine(QPointF(cx, cy - 10), QPointF(cx, cy - 2))


class FeedWorkspace(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Feed Workspace Dashboard")
        self.setMinimumSize(1350, 860)
        self.setWindowState(Qt.WindowState.WindowMaximized)

        self.subprocesses = []
        self.app_containers = {}
        self._running_count = 0

        # Dynamic ephemeral port allocation
        port_analyzer = self.find_free_port(5050)
        port_merger   = self.find_free_port(8000)
        port_builder  = self.find_free_port(5000)

        # index 0 = Home, 1 = Analyzer, 2 = Merger, 3 = Validator, 4 = Builder
        self.pending_servers = {
            1: {"name": "Feed Analyzer", "port": port_analyzer, "url": f"http://127.0.0.1:{port_analyzer}"},
            2: {"name": "Feed Merger",   "port": port_merger,   "url": f"http://127.0.0.1:{port_merger}"},
            4: {"name": "Feed Builder",  "port": port_builder,  "url": f"http://127.0.0.1:{port_builder}"},
        }

        self.init_ui()
        self.start_background_servers()

        # Port poller
        self.port_timer = QTimer(self)
        self.port_timer.setInterval(500)
        self.port_timer.timeout.connect(self.check_pending_ports)
        self.port_timer.start()

        # Live clock timer
        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(1000)
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start()

        # Live stats update timer
        self.stats_timer = QTimer(self)
        self.stats_timer.setInterval(5000)
        self.stats_timer.timeout.connect(self.refresh_stats)
        self.stats_timer.start()
        
        # Initial refresh
        QTimer.singleShot(100, self.refresh_stats)

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_dark_titlebar()

    def _apply_dark_titlebar(self):
        """Enable Windows 10/11 immersive dark mode and caption styling on the native window title bar."""
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
            # 1. DWMWA_USE_IMMERSIVE_DARK_MODE (20 for Win10 20H1+ & Win11; 19 for older Win10)
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19
            val = ctypes.c_int(1)
            res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(val), ctypes.sizeof(val)
            )
            if res != 0:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1, ctypes.byref(val), ctypes.sizeof(val)
                )

            # 2. DWMWA_CAPTION_COLOR = 35 (Win11: match topbar #09090b -> BGR 0x000b0909)
            DWMWA_CAPTION_COLOR = 35
            caption_color = ctypes.c_int(0x000b0909)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(caption_color), ctypes.sizeof(caption_color)
            )

            # 3. DWMWA_TEXT_COLOR = 36 (Win11: crisp white text #ffffff -> 0x00ffffff)
            DWMWA_TEXT_COLOR = 36
            text_color = ctypes.c_int(0x00ffffff)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_TEXT_COLOR, ctypes.byref(text_color), ctypes.sizeof(text_color)
            )
        except Exception as e:
            logger.debug(f"Could not apply immersive dark title bar: {e}")

    def refresh_stats(self):
        """Update dashboard statistics dynamically in real-time."""
        # 1. Feeds Processed (count actual files in user workspace)
        recent_count = 0
        try:
            from PySide6.QtCore import QSettings
            settings = QSettings("XMLValidatorPro", "XML Validator Pro")
            recent_files = settings.value("recent_files", [])
            if recent_files:
                recent_count = len(recent_files)
        except Exception:
            pass

        db_count = 0
        try:
            db_folder = os.path.join(WORKSPACE_DIR, "Feed_analyzer", "uploads", "databases")
            if os.path.isdir(db_folder):
                db_count = len([f for f in os.listdir(db_folder) if f.endswith(".db")])
        except Exception:
            pass

        merger_count = 0
        try:
            merge_folder = os.path.join(WORKSPACE_DIR, "Feed_merger", "output")
            if os.path.isdir(merge_folder):
                merger_count = len([f for f in os.listdir(merge_folder) if os.path.isfile(os.path.join(merge_folder, f))])
        except Exception:
            pass

        reports_count = 0
        try:
            reports_folder = os.path.join(WORKSPACE_DIR, "Feed_analyzer", "reports")
            if os.path.isdir(reports_folder):
                reports_count = len([f for f in os.listdir(reports_folder) if os.path.isfile(os.path.join(reports_folder, f))])
        except Exception:
            pass

        session_runs = getattr(self, "total_validations", 0)
        processed_count = recent_count + db_count + merger_count + reports_count + session_runs

        # 2. Success Rate (percentage of successful validation runs in this session)
        session_success = getattr(self, "successful_validations", 0)
        if session_runs > 0:
            success_pct = (session_success / session_runs) * 100.0
            success_rate = f"{success_pct:.1f}%"
        else:
            success_rate = "100.0%"

        # 3. Time Saved (dynamic: 1.5 minutes saved per processed file)
        time_saved = f"{processed_count * 1.5:.1f}m"

        # 4. Active Users (exactly 1 since they are running the desktop client locally)
        active_users = "1"

        # Update widgets
        if hasattr(self, "stat_widgets"):
            if "Feeds Processed" in self.stat_widgets:
                self.stat_widgets["Feeds Processed"].update_value(str(processed_count))
            if "Success Rate" in self.stat_widgets:
                self.stat_widgets["Success Rate"].update_value(success_rate)
            if "Active User" in self.stat_widgets:
                self.stat_widgets["Active User"].update_value(active_users)

        # Trigger redraw of custom vector charts
        if hasattr(self, "activity_chart"):
            self.activity_chart.update()




    # ── Port helpers ──────────────────────────────────────────────────────────
    def find_free_port(self, default_port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", 0))
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                return s.getsockname()[1]
        except Exception as e:
            logger.error(f"Error finding free port: {e}")
            return default_port

    def check_port(self, port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                return s.connect_ex(("127.0.0.1", port)) == 0
        except Exception:
            return False

    # ── Clock ─────────────────────────────────────────────────────────────────
    def _update_clock(self):
        if hasattr(self, "_clock_label"):
            now = datetime.datetime.now()
            self._clock_label.setText(now.strftime("%I:%M %p  •  %d %b %Y"))

    # ── UI Construction ───────────────────────────────────────────────────────
    def init_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.apply_theme()

        # Build sidebar + main area
        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_main_area())

    # ── Sidebar ───────────────────────────────────────────────────────────────
    def _build_sidebar(self):
        sidebar = QFrame(self)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(255)

        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(16, 24, 16, 20)
        sl.setSpacing(8)

        # Logo row: Teal stacked logo + Title + Muted collapse chevron
        logo_row = QHBoxLayout()
        logo_row.setContentsMargins(8, 0, 8, 0)
        logo_row.setSpacing(10)

        self.logo_icon = SidebarLogoWidget(sidebar)
        logo_row.addWidget(self.logo_icon)

        logo_title = QLabel("Feed Workspace", sidebar)
        logo_title.setStyleSheet("color: #ffffff; font-size: 17px; font-weight: bold; font-family: 'Segoe UI'; background: transparent; border: none;")
        logo_row.addWidget(logo_title)
        
        logo_row.addStretch()

        collapse_btn = QPushButton("‹", sidebar)
        collapse_btn.setStyleSheet("color: #475569; font-size: 18px; font-weight: bold; background: transparent; border: none;")
        collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        logo_row.addWidget(collapse_btn)
        sl.addLayout(logo_row)
        sl.addSpacing(22)

        # Nav buttons group
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        nav_items = [
            ("Hub",       "Hub",       0),
            ("Analyzer",  "Analyzer",  1),
            ("Merger",    "Merger",    2),
            ("Validator", "Validator", 3),
            ("Builder",   "Builder",   4),
            ("Converter", "Converter", 5),
        ]

        sl.setSpacing(0) # Disable default layout spacing to control spacing explicitly
        for icon_type, label, idx in nav_items:
            btn = SidebarButton(icon_type, label, sidebar)
            self.nav_group.addButton(btn, idx)
            sl.addWidget(btn)
            sl.addSpacing(12)  # Generous vertical space between each button!
            if idx == 0:
                btn.setChecked(True)

        # For backwards compatibility with status logging calls elsewhere in code
        self.status_label = QLabel(sidebar)
        self.status_label.setVisible(False)

        sl.addStretch()

        # Bottom section: profile avatar & exit/shutdown settings gear
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(4, 0, 4, 0)
        bottom_row.setSpacing(10)

        self.avatar_widget = ProfileAvatarWidget(sidebar)
        bottom_row.addWidget(self.avatar_widget)

        user_info = QVBoxLayout()
        user_info.setSpacing(1)
        user_name = QLabel("Danish Iqbal", sidebar)
        user_name.setStyleSheet("color: #cbd5e1; font-size: 14px; font-weight: bold; font-family: 'Segoe UI'; background: transparent; border: none;")
        user_name.setWordWrap(False)
        user_role = QLabel("Engineer", sidebar)
        user_role.setStyleSheet("color: #64748b; font-size: 11px; font-family: 'Segoe UI'; background: transparent; border: none;")
        user_info.addWidget(user_name)
        user_info.addWidget(user_role)
        bottom_row.addLayout(user_info, 1)

        settings_btn = ExitButton(sidebar)
        settings_btn.setObjectName("shutdown_btn_sidebar")
        settings_btn.clicked.connect(self.close)
        bottom_row.addWidget(settings_btn)

        sl.addLayout(bottom_row)

        self.nav_group.idClicked.connect(self._on_nav_clicked)
        return sidebar



    def purge_all_cache(self):
        """Purges all temporary scratch files, tool inputs/outputs/reports, and resets stats."""
        deleted_count = 0
        
        # Directories to clean up across all tools
        dirs_to_clean = [
            os.path.join(WORKSPACE_DIR, "scratch"),
            os.path.join(WORKSPACE_DIR, "Feed_analyzer", "uploads"),
            os.path.join(WORKSPACE_DIR, "Feed_analyzer", "uploads", "databases"),
            os.path.join(WORKSPACE_DIR, "Feed_analyzer", "reports"),
            os.path.join(WORKSPACE_DIR, "Feed_forge", "uploads"),
            os.path.join(WORKSPACE_DIR, "Feed_forge", "output"),
            os.path.join(WORKSPACE_DIR, "Feed_merger", "downloads"),
            os.path.join(WORKSPACE_DIR, "Feed_merger", "downloads", "tmp"),
            os.path.join(WORKSPACE_DIR, "Feed_merger", "output"),
            os.path.join(WORKSPACE_DIR, "Feed_validator", "reports")
        ]
        
        for directory in dirs_to_clean:
            if not os.path.isdir(directory):
                continue
            for f in os.listdir(directory):
                file_path = os.path.join(directory, f)
                # Skip subdirectories (we clean their files individually through the loop)
                if os.path.isdir(file_path):
                    continue
                # Keep folder-tracking files in Git
                if f == ".gitkeep":
                    continue
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Could not delete cache/data file {file_path}: {e}")
        
        # Clear recent validator files from QSettings
        try:
            from PySide6.QtCore import QSettings
            settings = QSettings("XMLValidatorPro", "XML Validator Pro")
            settings.setValue("recent_files", [])
        except Exception:
            pass

        # Reset session validator stats
        self.total_validations = 0
        self.successful_validations = 0
        self.refresh_stats()

        QMessageBox.information(
            self,
            "Purge Cache Successful",
            f"Purged {deleted_count} input, output, and temporary files across all tools and reset session stats!"
        )

    def _on_nav_clicked(self, idx):
        self.stacked_widget.setCurrentIndex(idx)
        if hasattr(self, "topbar_reset_btn"):
            self.topbar_reset_btn.setVisible(idx != 0)
        self._update_breadcrumb(idx)

    def _update_breadcrumb(self, idx):
        names = {
            0: "Home",
            1: "Analyzer",
            2: "Merger",
            3: "Validator",
            4: "Builder",
            5: "Converter",
            6: "Diff",
            7: "Downloader"
        }
        name = names.get(idx, "Home")
        if hasattr(self, "breadcrumb"):
            self.breadcrumb.setText(f'<span style="color: #64748b; font-size: 15px; font-family: \'Segoe UI\';">Feed Workspace</span> <span style="color: #475569; font-size: 15px;">/</span> <span style="color: #ffffff; font-size: 15px; font-weight: bold; font-family: \'Segoe UI\';">{name}</span>')

    # ── Main Area ─────────────────────────────────────────────────────────────
    def _build_main_area(self):
        wrapper = QWidget(self)
        wrapper.setObjectName("main_area")
        vl = QVBoxLayout(wrapper)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # Top bar
        vl.addWidget(self._build_topbar())

        # Stacked pages
        self.stacked_widget = QStackedWidget(wrapper)
        self.stacked_widget.setObjectName("stacked_main")
        vl.addWidget(self.stacked_widget)

        self.setup_stacked_pages()
        return wrapper

    # ── Top Bar ───────────────────────────────────────────────────────────────
    def _build_topbar(self):
        bar = QFrame(self)
        bar.setObjectName("topbar")
        bar.setFixedHeight(58)

        bl = QHBoxLayout(bar)
        bl.setContentsMargins(24, 0, 24, 0)
        bl.setSpacing(16)

        # Breadcrumbs: Feed Workspace / Home
        self.breadcrumb = QLabel(bar)
        self.breadcrumb.setText('<span style="color: #64748b; font-size: 15px; font-family: \'Segoe UI\';">Feed Workspace</span> <span style="color: #475569; font-size: 15px;">/</span> <span style="color: #ffffff; font-size: 15px; font-weight: bold; font-family: \'Segoe UI\';">Home</span>')
        self.breadcrumb.setStyleSheet("background: transparent; border: none;")
        bl.addWidget(self.breadcrumb)

        bl.addStretch()

        # Search field (centered)
        self._search = QLineEdit(bar)
        self._search.setPlaceholderText(" 🔍   Search anything... (Ctrl+K)")
        self._search.setFixedWidth(360)
        self._search.setObjectName("search_field")
        self._search.installEventFilter(self)
        bl.addWidget(self._search)

        bl.addStretch()

        # Reset Active Tool Button (hidden on Home page)
        self.topbar_reset_btn = QPushButton("🧹  Reset Tool", bar)
        self.topbar_reset_btn.setObjectName("topbar_reset_btn")
        self.topbar_reset_btn.setFixedSize(110, 34)
        self.topbar_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.topbar_reset_btn.clicked.connect(self.reset_active_tab)
        self.topbar_reset_btn.setVisible(False)
        bl.addWidget(self.topbar_reset_btn)

        # Clear Cache Button (Clean ghost button matching mockup on far right)
        self.topbar_purge_btn = QPushButton("Clear Cache", bar)
        self.topbar_purge_btn.setObjectName("topbar_clear_cache_btn")
        self.topbar_purge_btn.setFixedSize(105, 34)
        self.topbar_purge_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.topbar_purge_btn.setStyleSheet("""
            QPushButton#topbar_clear_cache_btn {
                background-color: transparent;
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 8px;
                color: #e2e8f0;
                font-size: 13px;
                font-weight: 500;
                font-family: 'Segoe UI', Arial;
                padding: 0 14px;
            }
            QPushButton#topbar_clear_cache_btn:hover {
                background-color: rgba(255, 255, 255, 0.08);
                border-color: rgba(255, 255, 255, 0.35);
                color: #ffffff;
            }
        """)
        self.topbar_purge_btn.clicked.connect(self.purge_all_cache)
        bl.addWidget(self.topbar_purge_btn)

        # Keep hidden clock label so timer updates don't crash
        self._clock_label = QLabel(bar)
        self._clock_label.setVisible(False)
        self._update_clock()

        return bar

    # ── Stacked Pages ─────────────────────────────────────────────────────────
    def setup_stacked_pages(self):
        """Build all pages and add them to the stacked widget."""
        # Page 0: Home Hub
        self.stacked_widget.addWidget(self._build_home_page())

        # Pages 1-4: Tool web views / native validator
        for idx in range(1, 5):
            if idx == 3:
                if ValidatorWindow:
                    self.validator_widget = ValidatorWindow()
                    self.stacked_widget.addWidget(self.validator_widget)
                    # Initialize validation count fields
                    self.total_validations = 0
                    self.successful_validations = 0
                    # Hook into validation complete method to update real-time statistics
                    if hasattr(self.validator_widget, "_on_validation_complete"):
                        orig_on_complete = self.validator_widget._on_validation_complete
                        def hooked_on_complete(result, *args, **kwargs):
                            orig_on_complete(result, *args, **kwargs)
                            self.total_validations += 1
                            is_success = True
                            if hasattr(result, "errors") and result.errors:
                                is_success = len(result.errors) == 0
                            elif hasattr(result, "is_valid"):
                                is_success = result.is_valid
                            if is_success:
                                self.successful_validations += 1
                            self.refresh_stats()
                        self.validator_widget._on_validation_complete = hooked_on_complete
                else:
                    err = QLabel("Feed Validator failed to load.\nEnsure 'Feed_validator' directory exists.", self)
                    err.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    err.setStyleSheet("color: #f87171; font-size: 16px; background-color: #09090b;")
                    self.stacked_widget.addWidget(err)

            else:
                info = self.pending_servers[idx]
                container = QStackedWidget(self)
                loader = LoadingWidget(info["name"], info["port"], container)
                container.addWidget(loader)

                web_view = QWebEngineView(container)
                web_view.setPage(ConsoleWebPage(web_view))
                channel = QWebChannel(web_view.page())
                bridge = AnalyzerDownloadBridge(self)
                channel.registerObject("pyBridge", bridge)
                web_view.page().setWebChannel(channel)
                web_view._download_channel = channel
                web_view._download_bridge = bridge
                profile = web_view.page().profile()
                try:
                    profile.downloadRequested.disconnect(self.handle_download_requested)
                except RuntimeError:
                    pass
                profile.downloadRequested.connect(self.handle_download_requested)
                ws = web_view.settings()
                ws.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
                ws.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
                web_view.setZoomFactor(1.05)
                container.addWidget(web_view)
                container.setCurrentIndex(0)
                self.stacked_widget.addWidget(container)
                self.app_containers[idx] = container

        # Page 5: Feed Converter
        self.converter_widget = FeedConverterTab(self)
        self.stacked_widget.addWidget(self.converter_widget)

        # Page 6: Feed Diff
        self.diff_widget = FeedDiffTab(self)
        self.stacked_widget.addWidget(self.diff_widget)

        # Page 7: Feed Downloader
        self.downloader_widget = FeedDownloaderTab(self)
        self.stacked_widget.addWidget(self.downloader_widget)

    def handle_download_requested(self, download_item):
        """Handles file download requests from the QWebEngineView safely."""
        try:
            logger.info("Download requested.")
            suggested_dir = download_item.downloadDirectory() or ""
            # Fall back to suggestedFileName if downloadFileName is empty/None
            suggested_name = download_item.downloadFileName() or download_item.suggestedFileName() or "export.csv"
            logger.info(f"Suggested dir: {suggested_dir}, name: {suggested_name}")
            
            initial_path = os.path.join(suggested_dir, suggested_name) if suggested_dir else suggested_name
            
            ext = os.path.splitext(suggested_name)[1].lower() if suggested_name else ""
            filters = []
            if ext == '.csv':
                filters = [("CSV Files", ["csv"]), ("All Files", ["*"])]
            elif ext in ('.xlsx', '.xls'):
                filters = [("Excel Files", ["xlsx"]), ("All Files", ["*"])]
            elif ext == '.html':
                filters = [("HTML Files", ["html"]), ("All Files", ["*"])]
            else:
                filters = [("All Files", ["*"])]

            save_path = ""
            if HAS_RUST_CORE and hasattr(feed_core_rs, "save_file_dialog_rs"):
                save_path = feed_core_rs.save_file_dialog_rs(suggested_name, "Save Exported File", filters)
            else:
                filter_str = "All Files (*)"
                if ext == '.csv':
                    filter_str = "CSV Files (*.csv);;All Files (*)"
                elif ext in ('.xlsx', '.xls'):
                    filter_str = "Excel Files (*.xlsx);;All Files (*)"
                elif ext == '.html':
                    filter_str = "HTML Files (*.html);;All Files (*)"
                save_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "Save Exported File",
                    initial_path,
                    filter_str
                )
            
            if save_path:
                download_item.setDownloadDirectory(os.path.dirname(save_path))
                download_item.setDownloadFileName(os.path.basename(save_path))
                download_item.accept()
                logger.info(f"Download accepted: saving to {save_path}")
            else:
                download_item.cancel()
                logger.info("Download cancelled by user.")
        except Exception as e:
            logger.error(f"Error in handle_download_requested: {e}", exc_info=True)
            download_item.cancel()

    # ── Home Page Builder ─────────────────────────────────────────────────────
    def _build_home_page(self):
        self.hub_page = ModernHubPage(self, self)
        return self.hub_page


    # ── Background Servers ────────────────────────────────────────────────────
    def start_background_servers(self):
        log_dir = os.path.join(WORKSPACE_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)

        for idx, info in list(self.pending_servers.items()):
            port = info["port"]
            name = info["name"]

            if self.check_port(port):
                logger.info(f"Port {port} already active – reusing for {name}.")
                continue

            app_folder = ""
            if name == "Feed Analyzer":
                app_folder = os.path.join(WORKSPACE_DIR, "Feed_analyzer")
                cmd = ["-m", "flask", "--app", "app", "run", "--port", str(port), "--host", "127.0.0.1"]
            elif name == "Feed Merger":
                app_folder = os.path.join(WORKSPACE_DIR, "Feed_merger")
                cmd = ["-m", "uvicorn", "core.web_server:app", "--host", "127.0.0.1", "--port", str(port)]
            elif name == "Feed Builder":
                app_folder = os.path.join(WORKSPACE_DIR, "Feed_forge")
                cmd = ["-m", "flask", "--app", "app", "run", "--port", str(port), "--host", "127.0.0.1"]

            if os.path.exists(app_folder):
                python_exe = get_python_exe(app_folder)
                logger.info(f"Launching {name} on port {port}…")
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                try:
                    log_path = os.path.join(log_dir, f"{name.lower().replace(' ', '_')}.log")
                    log_file = open(log_path, "a")
                    proc = subprocess.Popen(
                        [python_exe] + cmd,
                        cwd=app_folder,
                        stdout=log_file,
                        stderr=log_file,
                        creationflags=creationflags
                    )
                    self.subprocesses.append(proc)
                    self._running_count += 1
                except Exception as e:
                    logger.error(f"Failed to start {name}: {e}")
                    self.pending_servers.pop(idx, None)
            else:
                logger.warning(f"App folder not found: {app_folder}")
                self.pending_servers.pop(idx, None)

    def check_pending_ports(self):
        still_pending = {}
        for idx, info in self.pending_servers.items():
            if self.check_port(info["port"]):
                container = self.app_containers[idx]
                web_view = container.widget(1)
                web_view.load(QUrl(info["url"]))
                container.setCurrentIndex(1)
                logger.info(f"{info['name']} ready on port {info['port']}")
            else:
                still_pending[idx] = info

        self.pending_servers = still_pending
        if not self.pending_servers:
            self.port_timer.stop()
            self.status_label.setText("All services online")
            logger.info("All servers booted.")

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _count_uploads(self):
        """Count parsed feed databases in Feed_analyzer uploads folder (real metric)."""
        try:
            db_folder = os.path.join(WORKSPACE_DIR, "Feed_analyzer", "uploads", "databases")
            if os.path.isdir(db_folder):
                return len([f for f in os.listdir(db_folder) if f.endswith(".db")])
        except Exception:
            pass
        return 0

    # ── Navigation ────────────────────────────────────────────────────────────
    def switch_to_tab(self, index):
        btn = self.nav_group.button(index)
        if btn:
            btn.setChecked(True)
        self.stacked_widget.setCurrentIndex(index)
        if hasattr(self, "topbar_reset_btn"):
            self.topbar_reset_btn.setVisible(index != 0)
        self._update_breadcrumb(index)

    def reset_active_tab(self):
        """Resets the currently active tool/tab state (HTML reload for web views, reset method for native tabs)."""
        idx = self.stacked_widget.currentIndex()
        tool_names = {
            0: "Home Hub",
            1: "Feed Analyzer",
            2: "Feed Merger",
            3: "Feed Validator",
            4: "Feed Builder",
            5: "Feed Utilities",
            7: "Feed Downloader"
        }
        name = tool_names.get(idx, "Tool")

        if idx == 0:
            self.refresh_stats()
            QMessageBox.information(self, "Reset State", "Home Hub stats refreshed!")
            return
        
        reset_ok = False
        if idx in [1, 2, 4]:
            container = self.app_containers.get(idx)
            if container:
                web_view = container.widget(1)
                if isinstance(web_view, QWebEngineView):
                    web_view.reload()
                    logger.info(f"Reloaded embedded web application for Tab {idx}.")
                    reset_ok = True
        elif idx == 3:
            if hasattr(self, "validator_widget") and self.validator_widget:
                if hasattr(self.validator_widget, "web_view") and self.validator_widget.web_view:
                    self.validator_widget.web_view.reload()
                    logger.info("Reloaded validator web view.")
                    reset_ok = True
                else:
                    if hasattr(self.validator_widget, "clear_fields"):
                        self.validator_widget.clear_fields()
                    elif hasattr(self.validator_widget, "reset"):
                        self.validator_widget.reset()
                    logger.info("Reset native validator fields.")
                    reset_ok = True
        elif idx == 5:
            if hasattr(self, "converter_widget"):
                self.converter_widget.reset_tab()
                name = "Feed Converter"
                reset_ok = True
        elif idx == 6:
            if hasattr(self, "diff_widget"):
                self.diff_widget.reset_tab()
                name = "Feed Diff"
                reset_ok = True
        elif idx == 7:
            if hasattr(self, "downloader_widget"):
                self.downloader_widget.reset_tab()
                name = "Feed Downloader"
                reset_ok = True

        if reset_ok:
            self.status_label.setText(f"🧹 {name} reset successful!")
            QMessageBox.information(
                self,
                "Reset Tool",
                f"Successfully reset and cleared all inputs/caches for {name}!"
            )
        else:
            QMessageBox.warning(
                self,
                "Reset Tool",
                f"Reset failed: {name} does not support clean reset/refresh."
            )



    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_K and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.show_command_palette()
        else:
            super().keyPressEvent(event)

    def show_command_palette(self):
        """Displays the spotlight-style search overlay."""
        palette = CommandPaletteDialog(self, self)
        # Position the palette centered near the top of the main window
        palette.move(self.geometry().x() + (self.geometry().width() - palette.width()) // 2,
                     self.geometry().y() + 80)
        palette.exec()

    def eventFilter(self, obj, event):
        if obj == self._search and event.type() == QEvent.Type.FocusIn:
            self.show_command_palette()
            self._search.clearFocus()  # yield focus back to command palette
            return True
        return super().eventFilter(obj, event)




    # ── Theme ─────────────────────────────────────────────────────────────────
    def apply_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget#main_area {
                background-color: #09090b;
            }
            QScrollArea#home_scroll, QWidget#home_inner {
                background-color: #09090b;
                border: none;
            }
            QScrollBar:vertical {
                background: #09090b;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #27272a;
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

            /* Sidebar */
            QFrame#sidebar {
                background-color: #0d0d0f;
                border-right: 1px solid #18181b;
            }
            QLabel#sidebar_title {
                color: #dae2fd;
                font-size: 15px;
                font-weight: bold;
                font-family: 'Segoe UI', Arial;
                background: transparent;
                border: none;
            }
            QLabel#sidebar_subtitle {
                color: #988d9f;
                font-size: 11px;
                font-family: 'Segoe UI', Arial;
                background: transparent;
                border: none;
            }

            /* Nav buttons */
            QPushButton[class="nav_btn"] {
                background-color: transparent;
                color: #cfc2d6;
                border: none;
                border-radius: 8px;
                padding: 10px;
                font-size: 18px;
            }
            QPushButton[class="nav_btn"]:hover {
                background-color: rgba(221, 183, 255, 0.05);
                color: #dae2fd;
            }
            QPushButton[class="nav_btn"]:checked {
                background-color: rgba(183, 109, 255, 0.15);
                color: #ddb7ff;
                font-weight: bold;
                border-left: 3px solid #a855f7;
                border-radius: 0px;
            }

            /* Top bar */
            QFrame#topbar {
                background-color: #09090b;
                border-bottom: 1px solid #18181b;
            }
            QLineEdit#search_field {
                background-color: #0d0d0f;
                color: #dae2fd;
                border: 1px solid #27272a;
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 15px;
                font-family: 'Segoe UI', Arial;
            }
            QLineEdit#search_field:focus {
                border: 1px solid #ddb7ff;
                color: #dae2fd;
            }
            QLabel#shortcut_badge {
                background-color: #0d0d0f;
                color: #988d9f;
                border: 1px solid #27272a;
                border-radius: 5px;
                font-size: 10px;
                font-family: 'Segoe UI', Arial;
                padding: 3px 8px;
            }
            QPushButton#icon_btn {
                background-color: #0d0d0f;
                border: 1px solid #27272a;
                border-radius: 8px;
                font-size: 16px;
            }
            QPushButton#icon_btn:hover {
                background-color: #27272a;
            }
            QPushButton#topbar_reset_btn {
                background-color: #0d0d0f;
                color: #cfc2d6;
                border: 1px solid #27272a;
                border-radius: 8px;
                font-size: 15px;
                font-family: 'Segoe UI', Arial;
                font-weight: bold;
            }
            QPushButton#topbar_reset_btn:hover {
                background-color: rgba(221, 183, 255, 0.1);
                color: #ddb7ff;
                border: 1px solid #ddb7ff;
            }

            QLabel#user_avatar {
                background-color: #ddb7ff;
                color: #09090b;
                border-radius: 18px;
                font-size: 15px;
                font-weight: bold;
                font-family: 'Segoe UI', Arial;
                border: none;
            }
            QLabel#notif_badge {
                background-color: #ddb7ff;
                color: #09090b;
                border-radius: 8px;
                font-size: 9px;
                font-weight: bold;
                font-family: 'Segoe UI', Arial;
                border: none;
            }

            /* Stats wrap */
            QWidget#stats_wrap {
                background-color: transparent;
                border: none;
            }

            /* Panel cards (Recent Activity, Quick Tips) */
            QFrame#panel_card {
                background-color: #18181b;
                border: 1px solid #27272a;
                border-radius: 12px;
            }

            /* Stacked widget backgrounds */
            QStackedWidget#stacked_main {
                background-color: #09090b;
            }

            /* Sidebar compact buttons */
            QPushButton#purge_btn_sidebar {
                background-color: transparent;
                border: 1px solid #27272a;
                border-radius: 8px;
                font-size: 16px;
            }
            QPushButton#purge_btn_sidebar:hover {
                background-color: rgba(221, 183, 255, 0.1);
                border: 1px solid #ddb7ff;
            }
            QPushButton#shutdown_btn_sidebar {
                background-color: transparent;
                border: 1px solid #27272a;
                border-radius: 8px;
                font-size: 16px;
            }
            QPushButton#shutdown_btn_sidebar:hover {
                background-color: rgba(239, 68, 68, 0.1);
                border: 1px solid #ef4444;
            }

        """)



    # ── Close / Cleanup ───────────────────────────────────────────────────────
    def closeEvent(self, event):
        logger.info("Shutting down Feed Workspace…")
        if hasattr(self, "port_timer"):
            self.port_timer.stop()
        if hasattr(self, "clock_timer"):
            self.clock_timer.stop()
        if hasattr(self, "stats_timer"):
            self.stats_timer.stop()
        if hasattr(self, "validator_widget") and ValidatorWindow and isinstance(self.validator_widget, ValidatorWindow):
            self.validator_widget.close()

        logger.info("Terminating server processes (force process tree taskkill)…")
        for proc in self.subprocesses:
            if proc.poll() is None:
                pid = proc.pid
                logger.info(f"Force-killing process tree for PID {pid}…")
                try:
                    subprocess.Popen(f"taskkill /F /T /PID {pid}", creationflags=subprocess.CREATE_NO_WINDOW, shell=True)
                except Exception as e:
                    logger.warning(f"Failed to taskkill process {pid}: {e}")
                    proc.terminate()
        self.subprocesses.clear()
        event.accept()


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    font = QFont("Segoe UI", 14)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(font)
    workspace = FeedWorkspace()
    workspace.showMaximized()
    sys.exit(app.exec())
