"""
main_window.py – Redesigned BotBro chat UI

Key improvements:
  • Paper-clip / image button in the input bar (click → file dialog OR drag-drop anywhere)
  • Full-window drag-and-drop acceptance (setAcceptDrops on QMainWindow)
  • Cleaner, modern dark-mode look with subtle glass-morphism accents
  • Better typography, spacing and bubble styling
"""

import os
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QScrollArea, QSplitter,
    QSizePolicy, QFileDialog, QFrame,
)
from PyQt5.QtCore import Qt, QPropertyAnimation, pyqtSignal, QObject, QRect, QMimeData
from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QColor, QPalette, QFont

from gui.styles import MAIN_STYLESHEET, INPUT_STYLESHEET, VOICE_BTN_STYLESHEET, SCROLL_AREA_STYLESHEET
from gui.titlebar import TitleBar
from gui.sidebar import Sidebar
from gui.chat_bubble import ChatBubble

# Accepted image extensions
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff", ".tif"}

# ─────────────────────────────────────────────────────────────────────────────
# Image-input button (📎 paperclip)
# ─────────────────────────────────────────────────────────────────────────────
_ATTACH_BTN_STYLE = """
    QPushButton {
        background-color: #1e1e2e;
        color: #6c9ef8;
        border: 1.5px solid #2a2a3d;
        border-radius: 18px;
        font-size: 18px;
        padding: 0px;
    }
    QPushButton:hover {
        background-color: #252540;
        border-color: #6c9ef8;
        color: #a0c4ff;
    }
    QPushButton:pressed {
        background-color: #1a1a30;
    }
    QPushButton:disabled {
        background-color: #1a1a1a;
        color: #444;
        border-color: #333;
    }
"""

_VOICE_BTN_STYLE = """
    QPushButton {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #00AEEF, stop:1 #0070cc);
        color: white;
        border-radius: 18px;
        font-size: 16px;
        border: none;
    }
    QPushButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #00ccff, stop:1 #0090ee);
    }
    QPushButton:disabled {
        background-color: #2a2a2a;
        color: #555;
    }
"""

_INPUT_STYLE = """
    QLineEdit {
        background-color: #1a1a2e;
        color: #e8e8f0;
        border: 1.5px solid #2a2a3d;
        border-radius: 22px;
        padding: 10px 16px;
        font-size: 14px;
        font-family: "Segoe UI", "Inter", sans-serif;
        selection-background-color: #00AEEF44;
    }
    QLineEdit:focus {
        border: 1.5px solid #00AEEF;
        background-color: #1e1e38;
    }
    QLineEdit::placeholder {
        color: #484860;
    }
"""

# The subtle drag-over overlay hint shown at the bottom of the chat area
_DRAG_HINT_ACTIVE = """
    QLabel {
        color: #00d4ff;
        font-size: 13px;
        font-family: "Segoe UI", sans-serif;
        background: transparent;
        padding: 4px 0px;
    }
"""
_DRAG_HINT_IDLE = """
    QLabel {
        color: #2a2a4a;
        font-size: 12px;
        font-family: "Segoe UI", sans-serif;
        background: transparent;
        padding: 4px 0px;
    }
"""

_MAIN_WIDGET_STYLE = """
    #MainWidget {
        background-color: #0d0d1a;
        border-radius: 12px;
        border: 1px solid #1e1e35;
    }
    QSplitter::handle {
        background: #1a1a2a;
        width: 1px;
    }
"""

_SCROLL_STYLE = """
    QScrollArea {
        border: none;
        background-color: transparent;
    }
    QScrollBar:vertical {
        border: none;
        background: #0d0d1a;
        width: 6px;
        margin: 0px;
    }
    QScrollBar::handle:vertical {
        background: #2a2a4a;
        min-height: 24px;
        border-radius: 3px;
    }
    QScrollBar::handle:vertical:hover {
        background: #00AEEF66;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        border: none;
        background: none;
    }
"""


# ─────────────────────────────────────────────────────────────────────────────
# Signals
# ─────────────────────────────────────────────────────────────────────────────
class Signals(QObject):
    update_chat = pyqtSignal(str, str)
    status_update = pyqtSignal(str)


# ─────────────────────────────────────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────────────────────────────────────
class BotbroGUI(QMainWindow):
    def __init__(self, process_callback, voice_callback):
        super().__init__()
        self.process_callback = process_callback
        self.voice_callback = voice_callback
        self.signals = Signals()
        self._is_dragging = False

        self.signals.update_chat.connect(self._append_message)
        self.signals.status_update.connect(self._update_status)

        # Enable full-window drag-and-drop
        self.setAcceptDrops(True)

        self.init_ui()

    # ──────────────────────────────────────────────────────────────────────
    # UI construction
    # ──────────────────────────────────────────────────────────────────────
    def init_ui(self):
        self.resize(820, 660)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Root container
        main_widget = QWidget()
        main_widget.setObjectName("MainWidget")
        main_widget.setStyleSheet(_MAIN_WIDGET_STYLE)
        self.setCentralWidget(main_widget)

        root_layout = QVBoxLayout(main_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Title bar ──────────────────────────────────────────────────────
        self.title_bar = TitleBar(self)
        root_layout.addWidget(self.title_bar)

        # ── Splitter: sidebar | chat ───────────────────────────────────────
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(1)

        self.sidebar = Sidebar()
        self.sidebar.setMaximumWidth(180)
        self.splitter.addWidget(self.sidebar)

        # ── Chat column ───────────────────────────────────────────────────
        chat_widget = QWidget()
        chat_widget.setStyleSheet("background: transparent;")
        chat_col = QVBoxLayout(chat_widget)
        chat_col.setContentsMargins(14, 10, 14, 12)
        chat_col.setSpacing(6)

        # Scroll area for bubbles
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(_SCROLL_STYLE)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.chat_content = QWidget()
        self.chat_content.setStyleSheet("background: transparent;")
        self.chat_content_layout = QVBoxLayout(self.chat_content)
        self.chat_content_layout.setAlignment(Qt.AlignTop)
        self.chat_content_layout.setSpacing(8)
        self.scroll_area.setWidget(self.chat_content)
        chat_col.addWidget(self.scroll_area, 1)

        # Typing indicator
        self.typing_label = QLabel("● BotBro is thinking…")
        self.typing_label.setStyleSheet(
            "color: #00AEEF88; font-style: italic; font-size: 12px; padding: 2px 0;"
        )
        self.typing_label.hide()
        chat_col.addWidget(self.typing_label)

        # Drag hint (subtle, shown only when dragging)
        self.drag_hint = QLabel("🖼️  Drop image anywhere to sketch & draw it in Paint")
        self.drag_hint.setAlignment(Qt.AlignCenter)
        self.drag_hint.setStyleSheet(_DRAG_HINT_IDLE)
        chat_col.addWidget(self.drag_hint)

        # ── Input bar ─────────────────────────────────────────────────────
        input_frame = QFrame()
        input_frame.setStyleSheet("""
            QFrame {
                background-color: #111122;
                border: 1.5px solid #1e1e35;
                border-radius: 24px;
            }
        """)
        input_row = QHBoxLayout(input_frame)
        input_row.setContentsMargins(8, 6, 8, 6)
        input_row.setSpacing(6)

        # 📎 Attach image button
        self.attach_btn = QPushButton("📎")
        self.attach_btn.setFixedSize(40, 40)
        self.attach_btn.setStyleSheet(_ATTACH_BTN_STYLE)
        self.attach_btn.setToolTip("Attach an image to sketch & draw in Paint")
        self.attach_btn.setCursor(Qt.PointingHandCursor)
        self.attach_btn.clicked.connect(self._open_image_file_dialog)
        input_row.addWidget(self.attach_btn)

        # Text input
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Message BotBro…  (or attach 📎 / drop an image)")
        self.text_input.setStyleSheet(_INPUT_STYLE)
        self.text_input.setMinimumHeight(44)
        self.text_input.returnPressed.connect(self.handle_text_submit)
        input_row.addWidget(self.text_input, 1)

        # 🎤 Voice button
        self.voice_btn = QPushButton("🎤")
        self.voice_btn.setFixedSize(40, 40)
        self.voice_btn.setStyleSheet(_VOICE_BTN_STYLE)
        self.voice_btn.setCursor(Qt.PointingHandCursor)
        self.voice_btn.clicked.connect(self.handle_voice_click)
        input_row.addWidget(self.voice_btn)

        chat_col.addWidget(input_frame)

        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(
            "color: #333355; font-size: 10px; padding: 1px 4px;"
        )
        chat_col.addWidget(self.status_label)

        self.splitter.addWidget(chat_widget)
        self.splitter.setSizes([160, 660])

        root_layout.addWidget(self.splitter)

    # ──────────────────────────────────────────────────────────────────────
    # Drag-and-drop (whole window)
    # ──────────────────────────────────────────────────────────────────────
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                ext = Path(url.toLocalFile()).suffix.lower()
                if ext in _IMAGE_EXTS:
                    event.acceptProposedAction()
                    self._set_drag_active(True)
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drag_active(False)

    def dropEvent(self, event: QDropEvent):
        self._set_drag_active(False)
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if Path(local).suffix.lower() in _IMAGE_EXTS and os.path.isfile(local):
                event.acceptProposedAction()
                self._submit_image(local)
                return

    def _set_drag_active(self, active: bool):
        self._is_dragging = active
        if active:
            self.drag_hint.setStyleSheet(_DRAG_HINT_ACTIVE)
            self.drag_hint.setText("✨  Release to convert & draw in Paint!")
        else:
            self.drag_hint.setStyleSheet(_DRAG_HINT_IDLE)
            self.drag_hint.setText("🖼️  Drop image anywhere to sketch & draw it in Paint")

    # ──────────────────────────────────────────────────────────────────────
    # File dialog (📎 button)
    # ──────────────────────────────────────────────────────────────────────
    def _open_image_file_dialog(self):
        exts = " ".join(f"*{e}" for e in sorted(_IMAGE_EXTS))
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select an image to sketch & draw",
            os.path.expanduser("~"),
            f"Images ({exts});;All files (*.*)",
        )
        if path and os.path.isfile(path):
            self._submit_image(path)

    # ──────────────────────────────────────────────────────────────────────
    # Route image to the pipeline
    # ──────────────────────────────────────────────────────────────────────
    def _submit_image(self, image_path: str):
        display = os.path.basename(image_path)
        self._append_message("You", f"🖼️  Image: {display}")
        self._update_status("Converting image to sketch & drawing in Paint…")
        self.typing_label.show()
        self._set_controls_enabled(False)
        try:
            self.process_callback(f"__draw_local__:{image_path}")
        except Exception as err:
            self._append_message("System Error", str(err))
            self._update_status("Ready")

    # ──────────────────────────────────────────────────────────────────────
    # Chat helpers
    # ──────────────────────────────────────────────────────────────────────
    def _append_message(self, sender: str, message: str):
        self.typing_label.hide()
        bubble = ChatBubble(sender, message)
        self.chat_content_layout.addWidget(bubble)
        # Auto-scroll to bottom
        sb = self.scroll_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _update_status(self, status: str):
        self.status_label.setText(status)
        if status == "Ready" or status.startswith("System"):
            self._set_controls_enabled(True)
            self.typing_label.hide()
            if hasattr(self, "pulse_anim"):
                self.pulse_anim.stop()

    def _set_controls_enabled(self, enabled: bool):
        self.text_input.setEnabled(enabled)
        self.voice_btn.setEnabled(enabled)
        self.attach_btn.setEnabled(enabled)

    # ──────────────────────────────────────────────────────────────────────
    # Text submit
    # ──────────────────────────────────────────────────────────────────────
    def handle_text_submit(self):
        text = self.text_input.text().strip()
        if not text:
            return
        self.text_input.clear()
        self._append_message("You", text)
        self._update_status("Processing…")
        self.typing_label.show()
        try:
            self.process_callback(text)
        except Exception as err:
            self._append_message("System Error", str(err))
            self._update_status("Ready")

    # ──────────────────────────────────────────────────────────────────────
    # Voice
    # ──────────────────────────────────────────────────────────────────────
    def handle_voice_click(self):
        self._update_status("Listening…")
        self._set_controls_enabled(False)

        self.pulse_anim = QPropertyAnimation(self.voice_btn, b"geometry")
        self.pulse_anim.setDuration(500)
        r = self.voice_btn.geometry()
        self.pulse_anim.setStartValue(r)
        self.pulse_anim.setEndValue(QRect(r.x() - 2, r.y() - 2, r.width() + 4, r.height() + 4))
        self.pulse_anim.setLoopCount(-1)
        self.pulse_anim.start()

        try:
            self.voice_callback()
        except Exception as err:
            self._append_message("System Error", str(err))
            self._update_status("Ready")
