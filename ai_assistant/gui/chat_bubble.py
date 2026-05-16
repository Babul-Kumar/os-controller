"""chat_bubble.py – Premium dark-mode chat bubbles."""

from datetime import datetime
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QFont

try:
    import markdown as _md
    _HAS_MARKDOWN = True
except ImportError:
    _HAS_MARKDOWN = False

# ── Palette ───────────────────────────────────────────────────────────────────
_USER_BG   = "#1565c0"   # deep blue gradient start
_USER_BG2  = "#1976d2"
_BOT_BG    = "#1a1a2e"   # dark navy
_BOT_BG2   = "#16213e"
_TEXT      = "#e8e8f4"
_MUTED     = "#556070"
_SYS_BG    = "#2a1a1a"
_SYS_TEXT  = "#ff7070"

_BASE_FONT = '"Segoe UI", "Inter", "Arial", sans-serif'

# ─────────────────────────────────────────────────────────────────────────────

class ChatBubble(QWidget):
    def __init__(self, sender: str, message: str):
        super().__init__()
        self.sender_name = sender
        self.message = message
        self._build_ui()

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 3, 8, 3)

        # ── Bubble container ──────────────────────────────────────────────
        bubble = QWidget()
        bubble.setMaximumWidth(540)
        b_layout = QVBoxLayout(bubble)
        b_layout.setContentsMargins(14, 10, 14, 8)
        b_layout.setSpacing(4)

        # Sender tag (small, muted)
        if self.sender_name not in ("You",):
            name_lbl = QLabel(self.sender_name)
            name_lbl.setStyleSheet(
                f"color: #00AEEF; font-size: 10px; font-weight: 600; "
                f"font-family: {_BASE_FONT}; background: transparent;"
            )
            b_layout.addWidget(name_lbl)

        # Message text
        html = self._render_markdown(self.message)
        text_lbl = QLabel(html)
        text_lbl.setWordWrap(True)
        text_lbl.setTextFormat(Qt.RichText)
        text_lbl.setOpenExternalLinks(True)
        text_lbl.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse
        )
        text_lbl.setStyleSheet(f"background: transparent; color: {_TEXT};")
        b_layout.addWidget(text_lbl)

        # Timestamp
        ts = datetime.now().strftime("%I:%M %p")
        ts_lbl = QLabel(ts)
        ts_lbl.setAlignment(Qt.AlignRight)
        ts_lbl.setStyleSheet(
            f"color: {_MUTED}; font-size: 10px; background: transparent;"
        )
        b_layout.addWidget(ts_lbl)

        # ── Bubble style per sender ───────────────────────────────────────
        is_user = self.sender_name == "You"
        is_sys  = "error" in self.sender_name.lower() or "system" in self.sender_name.lower()

        if is_sys:
            bubble.setStyleSheet(f"""
                QWidget {{
                    background-color: {_SYS_BG};
                    border-radius: 14px;
                    border: 1px solid #5a1010;
                }}
            """)
            text_lbl.setStyleSheet(f"background: transparent; color: {_SYS_TEXT};")
        elif is_user:
            bubble.setStyleSheet(f"""
                QWidget {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 {_USER_BG}, stop:1 {_USER_BG2});
                    border-radius: 18px;
                    border-bottom-right-radius: 4px;
                }}
            """)
        else:
            bubble.setStyleSheet(f"""
                QWidget {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 {_BOT_BG}, stop:1 {_BOT_BG2});
                    border-radius: 18px;
                    border-bottom-left-radius: 4px;
                    border: 1px solid #252540;
                }}
            """)

        # ── Layout: user → right, bot → left ─────────────────────────────
        if is_user:
            outer.addStretch()
            outer.addWidget(bubble)
        else:
            outer.addWidget(bubble)
            outer.addStretch()

        # ── Subtle slide-in animation ─────────────────────────────────────
        self.anim = QPropertyAnimation(bubble, b"maximumWidth")
        self.anim.setDuration(180)
        self.anim.setStartValue(0)
        self.anim.setEndValue(540)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.start()

    def _render_markdown(self, text: str) -> str:
        style = (
            f'color:{_TEXT}; font-family:{_BASE_FONT}; '
            f'font-size:14px; line-height:1.5;'
        )
        if _HAS_MARKDOWN:
            try:
                html = _md.markdown(text, extensions=["nl2br"])
                return f'<div style="{style}">{html}</div>'
            except Exception:
                pass
        # Plain text fallback
        escaped = (
            text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br>")
        )
        return f'<div style="{style}">{escaped}</div>'
