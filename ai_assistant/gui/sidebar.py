"""sidebar.py – Slim, premium dark sidebar."""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QFrame
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont


_SIDEBAR_BG   = "#0a0a18"
_ITEM_HOVER   = "#151530"
_ACCENT       = "#00AEEF"
_TEXT_DIM     = "#4a4a6a"
_TEXT_NORMAL  = "#8888aa"
_TEXT_BRIGHT  = "#ccccee"


class Sidebar(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumWidth(130)
        self.setMaximumWidth(190)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {_SIDEBAR_BG};
                border-bottom-left-radius: 12px;
            }}
        """)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 18, 12, 18)
        layout.setSpacing(4)

        # Logo / branding
        logo = QLabel("🤖 BotBro")
        logo.setStyleSheet(f"""
            color: {_ACCENT};
            font-size: 15px;
            font-weight: 700;
            font-family: "Segoe UI", sans-serif;
            letter-spacing: 0.5px;
            padding-bottom: 10px;
        """)
        layout.addWidget(logo)

        # Thin separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: #1a1a2a; background: #1a1a2a; max-height: 1px;")
        layout.addWidget(sep)
        layout.addSpacing(8)

        # Nav buttons
        nav_items = [
            ("💬", "Chat"),
            ("🧠", "Memory"),
            ("🔌", "Plugins"),
            ("⚙️", "Settings"),
        ]
        for icon, label in nav_items:
            btn = QPushButton(f"  {icon}  {label}")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {_TEXT_NORMAL};
                    text-align: left;
                    padding: 9px 10px;
                    border-radius: 8px;
                    font-size: 13px;
                    font-family: "Segoe UI", sans-serif;
                    border: none;
                }}
                QPushButton:hover {{
                    background-color: {_ITEM_HOVER};
                    color: {_TEXT_BRIGHT};
                }}
                QPushButton:pressed {{
                    background-color: #1a1a38;
                }}
            """)
            btn.setCursor(Qt.PointingHandCursor)
            layout.addWidget(btn)

        layout.addStretch()

        # Divider
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("background: #1a1a2a; max-height: 1px;")
        layout.addWidget(sep2)
        layout.addSpacing(6)

        # Version tag
        ver = QLabel("v1.0.0")
        ver.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 10px; font-family: 'Segoe UI';")
        layout.addWidget(ver)
