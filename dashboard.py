import os
import sys
import socket
import subprocess
import logging
import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QTimer, QSize, QDateTime, QPoint, QPointF, QRectF, QEvent
from PySide6.QtGui import QFont, QIcon, QColor, QPainter, QPen, QLinearGradient, QBrush, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QStackedWidget, QLabel, QFrame, QButtonGroup,
    QGridLayout, QScrollArea, QLineEdit, QSizePolicy, QGraphicsDropShadowEffect,
    QComboBox, QFileDialog, QListWidget, QListWidgetItem, QDialog, QTextBrowser,
    QMessageBox
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage

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


# ── Quick Action Card ─────────────────────────────────────────────────────────
class QuickActionCard(QFrame):
    """Highly aesthetic bento-style Quick Action card with glowing radial border effects and tag badges."""
    CONFIGS = {
        "Feed Analyzer":  {"color": "#c084fc", "color_rgb": "192, 132, 252", "light": "#e9d5ff", "icon": "🔍", "tags": ["Heuristics", "Real-time"]},
        "Feed Merger":    {"color": "#fbbf24", "color_rgb": "251, 191, 36",  "light": "#fde68a", "icon": "🥞", "tags": ["Merge", "Mapping"]},
        "Feed Validator": {"color": "#38bdf8", "color_rgb": "56, 189, 248",  "light": "#bae6fd", "icon": "🛡️", "tags": ["Schema", "Compliance"]},
        "Feed Builder":   {"color": "#4ade80", "color_rgb": "74, 222, 128",  "light": "#bbf7d0", "icon": "🛠️", "tags": ["Composer", "Builder"]},
        "Feed Converter": {"color": "#a78bfa", "color_rgb": "167, 139, 250", "light": "#ddd6fe", "icon": "🔄", "tags": ["Convert", "Formats"]},
        "Feed Diff":      {"color": "#f472b6", "color_rgb": "244, 114, 182", "light": "#fbcfe8", "icon": "⚖️", "tags": ["Diff Check", "Mappers"]},
    }

    def __init__(self, title, description, tab_index, main_window, parent=None):
        super().__init__(parent)
        self.tab_index = tab_index
        self.main_window = main_window
        self.cfg = self.CONFIGS.get(title, {"color": "#7c3aed", "color_rgb": "124, 58, 237", "light": "#c084fc", "icon": "⚡", "tags": ["Tool"]})

        self.setObjectName("quick_card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(170)  # Make cards taller and bento-like
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # 1. Top Row: Icon Container and arrow indicator
        top_row = QHBoxLayout()
        
        # Rounded icon box with low-opacity theme background
        self.icon_box = QFrame(self)
        self.icon_box.setFixedSize(48, 48)
        self.icon_box.setStyleSheet(f"""
            QFrame {{
                background-color: rgba({self.cfg['color_rgb']}, 0.12);
                border: 1px solid rgba({self.cfg['color_rgb']}, 0.25);
                border-radius: 12px;
            }}
        """)
        box_lay = QVBoxLayout(self.icon_box)
        box_lay.setContentsMargins(0, 0, 0, 0)
        icon_lbl = QLabel(self.cfg["icon"], self.icon_box)
        icon_lbl.setStyleSheet(f"font-size: 20px; color: {self.cfg['color']}; background: transparent; border: none;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box_lay.addWidget(icon_lbl)
        top_row.addWidget(self.icon_box)

        top_row.addStretch()

        # Arrow indicator
        self.arrow_lbl = QLabel("↗", self)
        self.arrow_lbl.setStyleSheet("color: #4b5563; font-size: 18px; font-family: 'Segoe UI'; font-weight: bold; background: transparent; border: none;")
        top_row.addWidget(self.arrow_lbl)
        
        layout.addLayout(top_row)

        # 2. Middle Row: Title + Description
        self.title_lbl = QLabel(title, self)
        self.title_lbl.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {self.cfg['light']}; font-family: 'Segoe UI'; background: transparent; border: none;")
        layout.addWidget(self.title_lbl)

        self.desc_lbl = QLabel(description, self)
        self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setStyleSheet("color: #94a3b8; font-size: 13px; font-family: 'Segoe UI'; background: transparent; border: none;")
        layout.addWidget(self.desc_lbl)

        # Push elements apart
        layout.addStretch()

        # 3. Bottom Row: Small Chip Badges
        tags_row = QHBoxLayout()
        tags_row.setSpacing(6)
        for tag_text in self.cfg["tags"]:
            tag = QLabel(tag_text, self)
            tag.setStyleSheet(f"""
                QLabel {{
                    background-color: rgba({self.cfg['color_rgb']}, 0.08);
                    border: 1px solid rgba({self.cfg['color_rgb']}, 0.15);
                    border-radius: 6px;
                    padding: 3px 8px;
                    font-size: 10px;
                    color: {self.cfg['color']};
                    font-family: 'Segoe UI';
                    font-weight: bold;
                }}
            """)
            tags_row.addWidget(tag)
        tags_row.addStretch()
        layout.addLayout(tags_row)

        self.setStyleSheet(f"""
            QFrame#quick_card {{
                background-color: rgba(255, 255, 255, 0.02);
                border: 1px solid #27272a;
                border-radius: 16px;
            }}
            QFrame#quick_card:hover {{
                background-color: rgba({self.cfg['color_rgb']}, 0.04);
                border: 1px solid {self.cfg['color']};
            }}
        """)

    def enterEvent(self, event):
        self.arrow_lbl.setStyleSheet(f"color: {self.cfg['color']}; font-size: 18px; font-family: 'Segoe UI'; font-weight: bold; background: transparent; border: none;")
        # Light up the icon container on hover
        self.icon_box.setStyleSheet(f"""
            QFrame {{
                background-color: rgba({self.cfg['color_rgb']}, 0.22);
                border: 1px solid {self.cfg['color']};
                border-radius: 12px;
            }}
        """)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.arrow_lbl.setStyleSheet("color: #4b5563; font-size: 18px; font-family: 'Segoe UI'; font-weight: bold; background: transparent; border: none;")
        self.icon_box.setStyleSheet(f"""
            QFrame {{
                background-color: rgba({self.cfg['color_rgb']}, 0.12);
                border: 1px solid rgba({self.cfg['color_rgb']}, 0.25);
                border-radius: 12px;
            }}
        """)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.main_window.switch_to_tab(self.tab_index)
        else:
            super().mousePressEvent(event)
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
    """Format transformer tab: XML, JSON, and CSV multi-way converter with URL support."""
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName("converter_tab")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 32, 32, 32)
        lay.setSpacing(20)

        # Header block
        header = QVBoxLayout()
        header.setSpacing(4)
        title_lbl = QLabel("Feed Converter 🔄", self)
        title_lbl.setStyleSheet("color: #8b5cf6; font-size: 24px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;")
        header.addWidget(title_lbl)
        sub_lbl = QLabel("Transform XML, JSON, and CSV data formats instantly. Load files locally or from a live URL.", self)
        sub_lbl.setStyleSheet("color: #64748b; font-size: 15px; font-family: 'Segoe UI'; background: transparent;")
        header.addWidget(sub_lbl)
        lay.addLayout(header)

        # Two Column Split Layout
        split_layout = QHBoxLayout()
        split_layout.setSpacing(24)

        # ── LEFT PANEL: Config and Inputs ──
        left_panel = QFrame(self)
        left_panel.setObjectName("panel_card")
        left_panel.setStyleSheet("QFrame#panel_card { background-color: #121214; border: 1px solid #27272a; border-radius: 12px; }")
        l_lay = QVBoxLayout(left_panel)
        l_lay.setContentsMargins(20, 20, 20, 20)
        l_lay.setSpacing(16)

        l_title = QLabel("SOURCE CONFIGURATION", left_panel)
        l_title.setStyleSheet("color: #8b5cf6; font-size: 11px; font-weight: bold; letter-spacing: 1px; font-family: 'Segoe UI';")
        l_lay.addWidget(l_title)

        # File Dropzone (smaller height)
        self.dropzone = DragDropLabel(left_panel)
        self.dropzone.setStyleSheet("""
            QFrame#drag_drop_zone {
                background-color: #09090b;
                border: 2px dashed #27272a;
                border-radius: 10px;
                min-height: 100px;
            }
        """)
        l_lay.addWidget(self.dropzone)

        # OR divider label
        or_divider = QLabel("— OR LOAD FROM LIVE URL —", left_panel)
        or_divider.setAlignment(Qt.AlignmentFlag.AlignCenter)
        or_divider.setStyleSheet("color: #4b5563; font-size: 10px; font-weight: bold; letter-spacing: 0.5px; font-family: 'Segoe UI';")
        l_lay.addWidget(or_divider)

        # URL Input Box
        url_row = QHBoxLayout()
        url_row.setSpacing(10)

        self.url_input = QLineEdit(left_panel)
        self.url_input.setPlaceholderText("Paste feed URL here (e.g. http://...)")
        self.url_input.setMinimumHeight(38)
        self.url_input.setStyleSheet("""
            QLineEdit {
                background-color: #09090b;
                color: #f1f5f9;
                border: 1px solid #27272a;
                border-radius: 8px;
                padding-left: 10px;
                font-size: 15px;
                font-family: 'Segoe UI';
            }
            QLineEdit:focus {
                border: 1px solid #8b5cf6;
            }
        """)
        url_row.addWidget(self.url_input)

        self.fetch_btn = QPushButton("Fetch URL", left_panel)
        self.fetch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fetch_btn.setMinimumHeight(38)
        self.fetch_btn.setFixedWidth(100)
        self.fetch_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e3a8a;
                color: #60a5fa;
                border: 1px solid #3b82f6;
                border-radius: 8px;
                font-weight: bold;
                font-size: 12px;
                font-family: 'Segoe UI';
            }
            QPushButton:hover {
                background-color: #2563eb;
                color: #ffffff;
            }
        """)
        self.fetch_btn.clicked.connect(self.fetch_from_url)
        url_row.addWidget(self.fetch_btn)
        l_lay.addLayout(url_row)

        # Target Format Selectors
        format_row = QHBoxLayout()
        format_lbl = QLabel("Target Format:", left_panel)
        format_lbl.setStyleSheet("color: #cbd5e1; font-size: 15px; font-weight: bold; font-family: 'Segoe UI';")
        format_row.addWidget(format_lbl)

        self.format_combo = QComboBox(left_panel)
        self.format_combo.addItems(["JSON", "XML", "CSV"])
        self.format_combo.setFixedWidth(120)
        self.format_combo.setMinimumHeight(36)
        self.format_combo.setStyleSheet("""
            QComboBox {
                background-color: #09090b;
                color: #f1f5f9;
                border: 1px solid #27272a;
                border-radius: 8px;
                padding-left: 10px;
                font-size: 15px;
                font-family: 'Segoe UI';
            }
            QComboBox::drop-down {
                border: none;
                width: 25px;
            }
            QComboBox QAbstractItemView {
                background-color: #09090b;
                color: #f1f5f9;
                selection-background-color: #8b5cf6;
                border: 1px solid #27272a;
            }
        """)
        format_row.addWidget(self.format_combo)
        format_row.addStretch()
        l_lay.addLayout(format_row)

        # Action Buttons Row
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.convert_btn = QPushButton("Convert Source Feed  ⚡", left_panel)
        self.convert_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.convert_btn.setMinimumHeight(44)
        self.convert_btn.setStyleSheet("""
            QPushButton {
                background-color: #8b5cf6;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
                font-family: 'Segoe UI';
            }
            QPushButton:hover {
                background-color: #7c3aed;
            }
        """)
        self.convert_btn.clicked.connect(self.run_conversion)
        action_row.addWidget(self.convert_btn, 2)

        self.reset_btn = QPushButton("Reset Tab 🧹", left_panel)
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

        l_lay.addLayout(action_row)


        split_layout.addWidget(left_panel, 1)

        # ── RIGHT PANEL: Outputs & Details ──
        right_panel = QFrame(self)
        right_panel.setObjectName("panel_card")
        right_panel.setStyleSheet("QFrame#panel_card { background-color: #121214; border: 1px solid #27272a; border-radius: 12px; }")
        r_lay = QVBoxLayout(right_panel)
        r_lay.setContentsMargins(20, 20, 20, 20)
        r_lay.setSpacing(16)

        r_title = QLabel("CONVERSION CONSOLE & RESULTS", right_panel)
        r_title.setStyleSheet("color: #10b981; font-size: 11px; font-weight: bold; letter-spacing: 1px; font-family: 'Segoe UI';")
        r_lay.addWidget(r_title)

        # Logs terminal
        self.log_viewer = QTextBrowser(right_panel)
        self.log_viewer.setMinimumHeight(180)
        self.log_viewer.setStyleSheet("""
            QTextBrowser {
                background-color: #09090b;
                color: #10b981;
                border: 1px solid #27272a;
                border-radius: 8px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                padding: 12px;
            }
        """)
        r_lay.addWidget(self.log_viewer)

        # Converted Result card (initially hidden or empty)
        self.result_card = QFrame(right_panel)
        self.result_card.setStyleSheet("""
            QFrame {
                background-color: rgba(16, 185, 129, 0.04);
                border: 1px solid rgba(16, 185, 129, 0.2);
                border-radius: 10px;
                padding: 10px;
            }
        """)
        rc_lay = QVBoxLayout(self.result_card)
        rc_lay.setSpacing(8)

        rc_title = QLabel("🎉 Output File Ready", self.result_card)
        rc_title.setStyleSheet("color: #10b981; font-weight: bold; font-size: 15px; font-family: 'Segoe UI'; border: none; background: transparent;")
        rc_lay.addWidget(rc_title)

        self.rc_path = QLabel("", self.result_card)
        self.rc_path.setStyleSheet("color: #94a3b8; font-size: 11px; font-family: 'Consolas'; border: none; background: transparent;")
        self.rc_path.setWordWrap(True)
        rc_lay.addWidget(self.rc_path)

        # Action Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.open_folder_btn = QPushButton("Open Folder 📂", self.result_card)
        self.open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_folder_btn.setMinimumHeight(32)
        self.open_folder_btn.setStyleSheet("""
            QPushButton {
                background-color: #27272a;
                color: #cbd5e1;
                border: 1px solid #3f3f46;
                border-radius: 6px;
                font-size: 12px;
                font-family: 'Segoe UI';
            }
            QPushButton:hover {
                background-color: #3f3f46;
                color: #ffffff;
            }
        """)
        self.open_folder_btn.clicked.connect(self.open_output_folder)
        btn_row.addWidget(self.open_folder_btn)

        self.view_file_btn = QPushButton("View File 📄", self.result_card)
        self.view_file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_file_btn.setMinimumHeight(32)
        self.view_file_btn.setStyleSheet("""
            QPushButton {
                background-color: #27272a;
                color: #cbd5e1;
                border: 1px solid #3f3f46;
                border-radius: 6px;
                font-size: 12px;
                font-family: 'Segoe UI';
            }
            QPushButton:hover {
                background-color: #3f3f46;
                color: #ffffff;
            }
        """)
        self.view_file_btn.clicked.connect(self.open_output_file)
        btn_row.addWidget(self.view_file_btn)
        
        rc_lay.addLayout(btn_row)
        self.result_card.setVisible(False)
        r_lay.addWidget(self.result_card)

        # Converted Preview Card
        self.preview_card = QFrame(right_panel)
        self.preview_card.setStyleSheet("""
            QFrame {
                background-color: #09090b;
                border: 1px solid #27272a;
                border-radius: 10px;
                padding: 12px;
            }
        """)
        pc_lay = QVBoxLayout(self.preview_card)
        pc_lay.setContentsMargins(10, 10, 10, 10)
        pc_lay.setSpacing(10)

        pc_title = QLabel("📄 Output Preview", self.preview_card)
        pc_title.setStyleSheet("color: #8b5cf6; font-weight: bold; font-size: 15px; font-family: 'Segoe UI'; border: none; background: transparent;")
        pc_lay.addWidget(pc_title)

        self.preview_viewer = QTextBrowser(self.preview_card)
        self.preview_viewer.setMinimumHeight(240)
        self.preview_viewer.setStyleSheet("""
            QTextBrowser {
                background-color: #09090b;
                color: #e2e8f0;
                border: 1px solid #27272a;
                border-radius: 6px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                padding: 8px;
            }
        """)
        self.preview_viewer.setPlaceholderText("No preview available. Run conversion to generate output preview.")
        pc_lay.addWidget(self.preview_viewer)
        r_lay.addWidget(self.preview_card)

        split_layout.addWidget(right_panel, 1)
        lay.addLayout(split_layout)

        # Store converted path
        self.last_converted_path = None


    def fetch_from_url(self):
        url = self.url_input.text().strip()
        if not url:
            self.log_viewer.setHtml("<span style='color:#ef4444;'>[Error] Please enter a URL first.</span>")
            return

        self.log_viewer.append(f"[*] Downloading feed from URL: {url}...")
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("Fetching...")
        QApplication.processEvents()

        try:
            import urllib.request
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = response.read().decode('utf-8')

            # Create scratch directory inside workspace to store the fetched file
            scratch_dir = os.path.join(WORKSPACE_DIR, "scratch")
            os.makedirs(scratch_dir, exist_ok=True)
            
            # Save downloaded file
            ext = ".xml"
            if "json" in url.lower(): ext = ".json"
            elif "csv" in url.lower(): ext = ".csv"
            
            temp_path = os.path.join(scratch_dir, f"converter_fetched_feed{ext}")
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(data)

            self.dropzone.set_file(temp_path)
            self.log_viewer.append("<span style='color:#10b981;'>[Success] Feed URL fetched and loaded successfully!</span>")
        except Exception as e:
            self.log_viewer.append(f"<span style='color:#ef4444;'>[Error] Failed to fetch URL: {str(e)}</span>")
        finally:
            self.fetch_btn.setEnabled(True)
            self.fetch_btn.setText("Fetch URL")

    def run_conversion(self):
        input_path = self.dropzone.file_path
        if not input_path:
            self.log_viewer.setHtml("<span style='color:#ef4444;'>[Error] Please select/drop a local feed file or fetch from a URL first.</span>")
            return

        target_format = self.format_combo.currentText().lower()
        self.log_viewer.append(f"[*] Reading source file: {os.path.basename(input_path)}")
        
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            # Detect input format
            src_name = os.path.basename(input_path).lower()
            if src_name.endswith('.xml'):
                src_format = 'xml'
            elif src_name.endswith('.json'):
                src_format = 'json'
            elif src_name.endswith('.csv') or src_name.endswith('.txt'):
                src_format = 'csv'
            else:
                if content.startswith('<'): src_format = 'xml'
                elif content.startswith('{') or content.startswith('['): src_format = 'json'
                else: src_format = 'csv'

            self.log_viewer.append(f"[*] Detected source format: {src_format.upper()}")
            
            if src_format == target_format:
                self.log_viewer.append(f"<span style='color:#fbbf24;'>[Warning] File is already in {target_format.upper()} format.</span>")
                return

            self.log_viewer.append(f"[*] Executing transformation to {target_format.upper()}...")
            
            # Conversion Logic
            output_content = ""
            if src_format == 'csv':
                if target_format == 'json':
                    output_content = self.csv_to_json(content)
                elif target_format == 'xml':
                    output_content = self.csv_to_xml(content)
            elif src_format == 'json':
                if target_format == 'csv':
                    output_content = self.json_to_csv(content)
                elif target_format == 'xml':
                    output_content = self.json_to_xml(content)
            elif src_format == 'xml':
                if target_format == 'json':
                    output_content = self.xml_to_json(content)
                elif target_format == 'csv':
                    json_tmp = self.xml_to_json(content)
                    output_content = self.json_to_csv(json_tmp)

            # Save converted file
            dir_name = os.path.dirname(input_path)
            # Avoid naming everything 'converter_fetched_feed' if downloaded from URL
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            if base_name == "converter_fetched_feed":
                base_name = "fetched_feed"
            output_name = f"{base_name}_converted.{target_format}"
            output_path = os.path.join(dir_name, output_name)

            with open(output_path, 'w', encoding='utf-8') as out_f:
                out_f.write(output_content)

            self.last_converted_path = output_path
            self.rc_path.setText(output_path)
            self.result_card.setVisible(True)

            # Load file preview (first 4000 chars)
            try:
                with open(output_path, 'r', encoding='utf-8') as pf:
                    preview_txt = pf.read(4000)
                if os.path.getsize(output_path) > 4000:
                    preview_txt += "\n\n... [Truncated. Click 'View File' to open full file] ..."
                self.preview_viewer.setText(preview_txt)
            except Exception as pe:
                self.preview_viewer.setText(f"[Error loading preview: {str(pe)}]")

            self.log_viewer.append(f"<span style='color:#10b981;'>[Success] File successfully converted and saved!</span>")
            self.log_viewer.append(f"Output File: <a href='file:///{output_path}' style='color:#60a5fa;'>{output_name}</a>")

            
            # Increment dynamic session stats
            if hasattr(self.main_window, "total_validations"):
                self.main_window.total_validations += 1
                self.main_window.successful_validations += 1
                self.main_window.refresh_stats()

        except Exception as e:
            self.log_viewer.append(f"<span style='color:#ef4444;'>[Error] Conversion failed: {str(e)}</span>")

    def open_output_folder(self):
        if self.last_converted_path and os.path.exists(self.last_converted_path):
            folder = os.path.dirname(self.last_converted_path)
            os.startfile(folder)

    def open_output_file(self):
        if self.last_converted_path and os.path.exists(self.last_converted_path):
            os.startfile(self.last_converted_path)

    def reset_tab(self):
        """Resets the tab inputs, preview console, and deletes temporary downloaded files."""
        # Reset dropzone
        self.dropzone.file_path = None
        self.dropzone.icon_lbl.setText("📥")
        self.dropzone.text_lbl.setText("Drag & Drop your Feed file here\n(or click to browse)")
        self.dropzone.setStyleSheet("""
            QFrame#drag_drop_zone {
                background-color: #121214;
                border: 2px dashed #334155;
                border-radius: 12px;
                min-height: 140px;
            }
        """)

        # Clear inputs & displays
        self.url_input.clear()
        self.log_viewer.clear()
        self.preview_viewer.clear()
        self.preview_viewer.setPlaceholderText("No preview available. Run conversion to generate output preview.")
        self.result_card.setVisible(False)

        # Delete downloaded file specifically for this tab
        try:
            temp_path = os.path.join(WORKSPACE_DIR, "scratch", "converter_fetched_feed.xml")
            if os.path.isfile(temp_path):
                os.remove(temp_path)
            temp_path_json = os.path.join(WORKSPACE_DIR, "scratch", "converter_fetched_feed.json")
            if os.path.isfile(temp_path_json):
                os.remove(temp_path_json)
            temp_path_csv = os.path.join(WORKSPACE_DIR, "scratch", "converter_fetched_feed.csv")
            if os.path.isfile(temp_path_csv):
                os.remove(temp_path_csv)
        except Exception as e:
            logger.warning(f"Could not remove converter scratch files: {e}")

        self.log_viewer.append("[*] Tab state cleared and downloaded files purged successfully.")


    def xml_to_json(self, xml_str):
        import xml.etree.ElementTree as ET
        import json
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
            if elem.text:
                text = elem.text.strip()
                if children or elem.attrib:
                    if text:
                        d[elem.tag]['#text'] = text
                else:
                    d[elem.tag] = text
            return d
        root = ET.fromstring(xml_str)
        return json.dumps(elem_to_dict(root), indent=2)

    def json_to_xml(self, json_str):
        import json
        import xml.etree.ElementTree as ET
        data = json.loads(json_str)
        def build_xml(tag, d):
            elem = ET.Element(tag)
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
            else:
                elem.text = str(d)
            return elem
        if isinstance(data, dict) and len(data) == 1:
            root_key = list(data.keys())[0]
            root = build_xml(root_key, data[root_key])
        else:
            root = build_xml("root", data)
        return ET.tostring(root, encoding="utf-8").decode("utf-8")

    def csv_to_json(self, csv_str):
        import csv, io, json
        reader = csv.DictReader(io.StringIO(csv_str))
        return json.dumps([row for row in reader], indent=2)

    def csv_to_xml(self, csv_str):
        import csv, io
        import xml.etree.ElementTree as ET
        reader = csv.DictReader(io.StringIO(csv_str))
        root = ET.Element("feed")
        for row in reader:
            item = ET.SubElement(root, "item")
            for k, v in row.items():
                tag_name = "".join(c for c in k if c.isalnum() or c in "_-")
                if not tag_name: tag_name = "field"
                sub = ET.SubElement(item, tag_name)
                sub.text = str(v)
        return ET.tostring(root, encoding="utf-8").decode("utf-8")

    def json_to_csv(self, json_str):
        import json, csv, io
        data = json.loads(json_str)
        if not isinstance(data, list):
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        data = v
                        break
                else:
                    data = [data]
        output = io.StringIO()
        if data and isinstance(data, list) and isinstance(data[0], dict):
            keys = data[0].keys()
            writer = csv.DictWriter(output, fieldnames=keys)
            writer.writeheader()
            for row in data:
                writer.writerow(row)
        return output.getvalue()


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
        sidebar.setFixedWidth(230)

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
            ("Diff",      "Diff",      6),
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
        bottom_row.setContentsMargins(8, 0, 8, 0)
        bottom_row.setSpacing(12)

        self.avatar_widget = ProfileAvatarWidget(sidebar)
        bottom_row.addWidget(self.avatar_widget)

        user_info = QVBoxLayout()
        user_info.setSpacing(1)
        user_name = QLabel("Danish Iqbal", sidebar)
        user_name.setStyleSheet("color: #cbd5e1; font-size: 15px; font-weight: bold; font-family: 'Segoe UI'; background: transparent; border: none;")
        user_role = QLabel("Engineer", sidebar)
        user_role.setStyleSheet("color: #64748b; font-size: 11px; font-family: 'Segoe UI'; background: transparent; border: none;")
        user_info.addWidget(user_name)
        user_info.addWidget(user_role)
        bottom_row.addLayout(user_info)
        
        bottom_row.addStretch()

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
        breadcrumb = QLabel(bar)
        breadcrumb.setText('<span style="color: #64748b; font-size: 15px; font-family: \'Segoe UI\';">Feed Workspace</span> <span style="color: #475569; font-size: 15px;">/</span> <span style="color: #ffffff; font-size: 15px; font-weight: bold; font-family: \'Segoe UI\';">Home</span>')
        breadcrumb.setStyleSheet("background: transparent; border: none;")
        bl.addWidget(breadcrumb)

        bl.addStretch()

        # Search field (centered)
        self._search = QLineEdit(bar)
        self._search.setPlaceholderText(" 🔍   ⌘K Search anything...")
        self._search.setFixedWidth(280)
        self._search.setObjectName("search_field")
        self._search.installEventFilter(self)
        bl.addWidget(self._search)

        # Reset Active Tool Button
        self.topbar_reset_btn = QPushButton("🧹  Reset Tool", bar)
        self.topbar_reset_btn.setObjectName("topbar_reset_btn")
        self.topbar_reset_btn.setFixedSize(110, 36)
        self.topbar_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.topbar_reset_btn.clicked.connect(self.reset_active_tab)
        bl.addWidget(self.topbar_reset_btn)

        # Purge Cache Button
        self.topbar_purge_btn = QPushButton("🗑️  Purge Cache", bar)
        self.topbar_purge_btn.setObjectName("topbar_reset_btn")
        self.topbar_purge_btn.setFixedSize(110, 36)
        self.topbar_purge_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.topbar_purge_btn.clicked.connect(self.purge_all_cache)
        bl.addWidget(self.topbar_purge_btn)

        bl.addStretch()

        # Bell with notification badge
        bell_frame = QFrame(bar)
        bell_frame.setFixedSize(36, 36)
        bell_frame.setStyleSheet("background: transparent; border: none;")
        bell_btn = QPushButton("🔔", bell_frame)
        bell_btn.setObjectName("icon_btn")
        bell_btn.setFixedSize(36, 36)
        bell_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self._notif_badge = QLabel(bell_frame)
        self._notif_badge.setObjectName("notif_badge")
        self._notif_badge.setFixedSize(6, 6)
        self._notif_badge.move(24, 6)
        self._notif_badge.setStyleSheet("background-color: #ef4444; border-radius: 3px; border: none;")
        
        bl.addWidget(bell_frame)

        # Moon icon / Switch
        moon_btn = QPushButton("🌙", bar)
        moon_btn.setObjectName("icon_btn")
        moon_btn.setFixedSize(36, 36)
        moon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        bl.addWidget(moon_btn)

        # User info
        user_col = QVBoxLayout()
        user_col.setSpacing(1)
        hello_lbl = QLabel("Danish Iqbal", bar)
        hello_lbl.setStyleSheet("color: #ffffff; font-size: 15px; font-weight: bold; font-family: 'Segoe UI'; background: transparent; border: none;")
        user_col.addWidget(hello_lbl)
        
        role_lbl = QLabel("Engineer", bar)
        role_lbl.setStyleSheet("color: #64748b; font-size: 10px; font-family: 'Segoe UI'; background: transparent; border: none;")
        user_col.addWidget(role_lbl)
        bl.addLayout(user_col)

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
                ws = web_view.settings()
                ws.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
                ws.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
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



    # ── Home Page Builder ─────────────────────────────────────────────────────
    def _build_home_page(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setObjectName("home_scroll")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        home = QWidget()
        home.setObjectName("home_inner")
        hl = QVBoxLayout(home)
        hl.setContentsMargins(32, 32, 32, 32)
        hl.setSpacing(28)

        # ── Welcome + Stats Row ───────────────────────────────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(24)

        # Welcome text block
        welcome_block = QVBoxLayout()
        welcome_block.setSpacing(6)
        welcome_to = QLabel("Welcome to", home)
        welcome_to.setStyleSheet("color: #94a3b8; font-size: 16px; font-family: 'Segoe UI'; background: transparent; border: none;")
        welcome_block.addWidget(welcome_to)

        hub_title = QLabel("Feed Workspace Hub 🚀", home)
        hub_title.setStyleSheet("color: #f1f5f9; font-size: 34px; font-weight: bold; font-family: 'Segoe UI'; background: transparent; border: none;")
        welcome_block.addWidget(hub_title)

        sub_desc = QLabel("Powerful tools to analyze, merge, validate, and build\nyour feed data with speed and accuracy.", home)
        sub_desc.setStyleSheet("color: #64748b; font-size: 15px; line-height: 22px; font-family: 'Segoe UI'; background: transparent; border: none;")
        welcome_block.addWidget(sub_desc)
        welcome_block.addStretch()
        top_row.addLayout(welcome_block, 2)

        # Stats cards
        self.stat_widgets = {}
        uploads_count = self._count_uploads()
        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        stats_row.setContentsMargins(12, 8, 12, 8)
        for val, lbl in [
            (str(12 + uploads_count), "Feeds Processed"),
            ("98.5%",                 "Success Rate"),
            ("3.2s",                  "Avg Speed"),
            ("1",                     "Active User"),
        ]:
            card = StatCard(val, lbl, home)
            self.stat_widgets[lbl] = card
            stats_row.addWidget(card)

        stats_wrap = QWidget(home)
        stats_wrap.setObjectName("stats_wrap")
        stats_wrap.setLayout(stats_row)
        top_row.addWidget(stats_wrap, 3)
        hl.addLayout(top_row)

        # ── Quick Actions Grid (Full Width, 3 Columns) ────────────────────────
        grid_section = QFrame(home)
        grid_section.setObjectName("panel_card")
        gl = QVBoxLayout(grid_section)
        gl.setContentsMargins(24, 20, 24, 20)
        gl.setSpacing(16)

        grid_title = QLabel("Quick Actions", grid_section)
        grid_title.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: bold; font-family: 'Segoe UI'; background: transparent; border: none;")
        gl.addWidget(grid_title)

        grid_lay = QGridLayout()
        grid_lay.setSpacing(18)
        grid_lay.setRowStretch(0, 1)
        grid_lay.setRowStretch(1, 1)

        actions = [
            ("Feed Analyzer",  "Profile fields, parse schemas, and identify format anomalies", 1),
            ("Feed Merger",    "Combine multiple source files into a single, cohesive feed", 2),
            ("Feed Validator", "Run rule compliance and semantic integrity validation", 3),
            ("Feed Builder",   "Compose, edit, and generate feeds from scratch", 4),
            ("Feed Converter", "Convert feed schemas across JSON, XML, and CSV", 5),
            ("Feed Diff",      "Compare two feeds and map the schema differences", 6),
        ]

        for i, (title, desc, idx) in enumerate(actions):
            row = i // 3
            col = i % 3
            card = QuickActionCard(title, desc, idx, self, grid_section)
            grid_lay.addWidget(card, row, col)

        gl.addLayout(grid_lay)
        hl.addWidget(grid_section, 1)

        scroll.setWidget(home)
        return scroll

    # ── Recent Activity Panel ─────────────────────────────────────────────────
    def _build_recent_activity(self, parent):
        frame = QFrame(parent)
        frame.setObjectName("panel_card")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(20, 18, 20, 18)
        fl.setSpacing(14)

        title_row = QHBoxLayout()
        title_icon = QLabel("🕐", frame)
        title_icon.setStyleSheet("font-size: 16px; background: transparent; border: none; color: #94a3b8;")
        title_row.addWidget(title_icon)
        title_lbl = QLabel("Recent Activity", frame)
        title_lbl.setStyleSheet("color: #f1f5f9; font-size: 14px; font-weight: bold; font-family: 'Segoe UI'; background: transparent; border: none;")
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        fl.addLayout(title_row)

        # Divider
        d = QFrame(frame)
        d.setFrameShape(QFrame.Shape.HLine)
        d.setStyleSheet("background-color: #1c1c1f; max-height:1px; border:none;")
        fl.addWidget(d)

        # Badge colors as proper rgba() — hex+alpha doesn't render in Qt stylesheets
        activities = [
            ("sales_feed_2024.xml",       "Validated",
             "rgba(52,211,153,255)",  "rgba(52,211,153,28)",  "rgba(52,211,153,80)"),
            ("career_feed_merged.xml",    "Merged",
             "rgba(251,146,60,255)",  "rgba(251,146,60,28)",  "rgba(251,146,60,80)"),
            ("jobs_data.xlsx",            "Built",
             "rgba(96,165,250,255)",  "rgba(96,165,250,28)",  "rgba(96,165,250,80)"),
            ("std_feed_analysis.html",    "Analyzed",
             "rgba(192,132,252,255)", "rgba(192,132,252,28)", "rgba(192,132,252,80)"),
        ]
        times = ["2 min ago", "15 min ago", "32 min ago", "1 hr ago"]
        for i, (filename, action, text_col, bg_col, border_col) in enumerate(activities):
            row = QHBoxLayout()
            row.setSpacing(10)

            f_icon = QLabel("▸", frame)
            f_icon.setFixedWidth(14)
            f_icon.setStyleSheet("color: #334155; font-size: 15px; background: transparent; border: none;")
            row.addWidget(f_icon)

            fname = QLabel(filename, frame)
            fname.setStyleSheet("color: #cbd5e1; font-size: 12px; font-family: 'Segoe UI'; background: transparent; border: none;")
            row.addWidget(fname)
            row.addStretch()

            badge = QLabel(action, frame)
            badge.setStyleSheet(f"""
                color: {text_col};
                background-color: {bg_col};
                border: 1px solid {border_col};
                border-radius: 5px;
                font-size: 11px;
                font-weight: 600;
                font-family: 'Segoe UI';
                padding: 2px 10px;
            """)
            row.addWidget(badge)

            time_lbl = QLabel(times[i], frame)
            time_lbl.setStyleSheet("color: #475569; font-size: 11px; font-family: 'Segoe UI'; background: transparent; border: none;")
            time_lbl.setFixedWidth(70)
            time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(time_lbl)

            fl.addLayout(row)

        fl.addStretch()
        return frame

    # ── Quick Tips Panel ──────────────────────────────────────────────────────
    def _build_quick_tips(self, parent):
        frame = QFrame(parent)
        frame.setObjectName("panel_card")
        
        main_layout = QHBoxLayout(frame)
        main_layout.setContentsMargins(20, 18, 20, 18)
        main_layout.setSpacing(16)

        # Left Column: Tips text content
        left_col = QVBoxLayout()
        left_col.setSpacing(10)

        title_row = QHBoxLayout()
        tip_icon = QLabel("💡", frame)
        tip_icon.setStyleSheet("font-size: 16px; background: transparent; border: none;")
        title_row.addWidget(tip_icon)
        tip_title = QLabel("Quick Tips", frame)
        tip_title.setStyleSheet("color: #f1f5f9; font-size: 14px; font-weight: bold; font-family: 'Segoe UI'; background: transparent; border: none;")
        title_row.addWidget(tip_title)
        title_row.addStretch()
        left_col.addLayout(title_row)

        d = QFrame(frame)
        d.setFrameShape(QFrame.Shape.HLine)
        d.setStyleSheet("background-color: #27272a; max-height:1px; border:none;")
        left_col.addWidget(d)

        tips = [
            "Use Feed Analyzer to understand your data better.",
            "Merge feeds to eliminate duplicates and unify data.",
            "Always validate your feeds before publishing.",
            "Build custom feeds quickly using templates.",
        ]
        for tip in tips:
            row = QHBoxLayout()
            row.setSpacing(8)
            arrow = QLabel("▸", frame)
            arrow.setStyleSheet("color: #ec4899; font-size: 14px; font-weight: bold; background: transparent; border: none;")
            arrow.setFixedWidth(10)
            row.addWidget(arrow)
            tip_lbl = QLabel(tip, frame)
            tip_lbl.setWordWrap(True)
            tip_lbl.setStyleSheet("color: #94a3b8; font-size: 12px; font-family: 'Segoe UI'; background: transparent; border: none;")
            row.addWidget(tip_lbl)
            left_col.addLayout(row)

        left_col.addStretch()
        main_layout.addLayout(left_col, 3)

        # Right Column: The mockup illustration
        right_col = QVBoxLayout()
        right_col.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        img_lbl = QLabel(frame)
        img_lbl.setFixedSize(140, 115)
        pix = QPixmap("dashboard_tips_mockup.png")
        if not pix.isNull():
            img_lbl.setPixmap(pix.scaled(140, 115, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
        img_lbl.setStyleSheet("""
            border-radius: 8px;
            border: 1px solid #27272a;
        """)
        right_col.addWidget(img_lbl)
        
        main_layout.addLayout(right_col, 2)

        return frame


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

    def reset_active_tab(self):
        """Resets the currently active tool/tab state (HTML reload for web views, reset method for native tabs)."""
        idx = self.stacked_widget.currentIndex()
        tool_names = {
            0: "Home Hub",
            1: "Feed Analyzer",
            2: "Feed Merger",
            3: "Feed Validator",
            4: "Feed Builder",
            5: "Feed Utilities"
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
    app.setFont(font)
    workspace = FeedWorkspace()
    workspace.show()
    sys.exit(app.exec())
