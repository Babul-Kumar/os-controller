from datetime import datetime
import markdown
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, QPropertyAnimation, QRect
from PyQt5.QtGui import QFont

from gui.styles import USER_BUBBLE_COLOR, BOT_BUBBLE_COLOR, TEXT_COLOR, MUTED_TEXT_COLOR

class ChatBubble(QWidget):
    def __init__(self, sender: str, message: str):
        super().__init__()
        self.sender_name = sender
        self.message = message
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 5, 10, 5)

        # Container for the bubble text and timestamp
        bubble_container = QWidget()
        bubble_layout = QVBoxLayout(bubble_container)
        bubble_layout.setContentsMargins(15, 12, 15, 12)

        # Markdown Rendering
        try:
            # Basic markdown rendering without complex extensions for PyQt QLabel
            html_message = markdown.markdown(self.message)
            # Tweak font styles for HTML display within QLabel
            html_message = f'<div style="color: {TEXT_COLOR}; font-family: \'Segoe UI\', sans-serif; font-size: 14px;">{html_message}</div>'
        except Exception:
            html_message = self.message  # Fallback

        self.text_label = QLabel(html_message)
        self.text_label.setWordWrap(True)
        self.text_label.setTextFormat(Qt.RichText)
        self.text_label.setOpenExternalLinks(True)
        bubble_layout.addWidget(self.text_label)

        # Timestamp
        timestamp = datetime.now().strftime("%I:%M %p")
        self.time_label = QLabel(timestamp)
        self.time_label.setStyleSheet(f"color: {MUTED_TEXT_COLOR}; font-size: 10px;")
        self.time_label.setAlignment(Qt.AlignRight)
        bubble_layout.addWidget(self.time_label)

        # Styling
        if self.sender_name == "You":
            bubble_container.setStyleSheet(f"""
                QWidget {{
                    background-color: {USER_BUBBLE_COLOR};
                    border-radius: 15px;
                    border-bottom-right-radius: 0px;
                }}
            """)
            layout.addStretch()
            layout.addWidget(bubble_container)
        else:
            bubble_container.setStyleSheet(f"""
                QWidget {{
                    background-color: {BOT_BUBBLE_COLOR};
                    border-radius: 15px;
                    border-bottom-left-radius: 0px;
                }}
            """)
            layout.addWidget(bubble_container)
            layout.addStretch()

        self.setLayout(layout)

        # Fade-in animation
        self.setWindowOpacity(0.0)
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(300)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.start()
