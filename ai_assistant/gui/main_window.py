import sys
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLineEdit, QPushButton, QLabel, QScrollArea, QSplitter
)
from PyQt5.QtCore import Qt, QPropertyAnimation, pyqtSignal, QObject, QRect

from gui.styles import MAIN_STYLESHEET, INPUT_STYLESHEET, VOICE_BTN_STYLESHEET, SCROLL_AREA_STYLESHEET
from gui.titlebar import TitleBar
from gui.sidebar import Sidebar
from gui.chat_bubble import ChatBubble

class Signals(QObject):
    update_chat = pyqtSignal(str, str)
    status_update = pyqtSignal(str)

class BotbroGUI(QMainWindow):
    def __init__(self, process_callback, voice_callback):
        super().__init__()
        self.process_callback = process_callback
        self.voice_callback = voice_callback
        self.signals = Signals()
        
        self.signals.update_chat.connect(self._append_message)
        self.signals.status_update.connect(self._update_status)
        
        self.init_ui()

    def init_ui(self):
        self.resize(800, 600)
        
        # Frameless and translucent for modern look
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Main Layout Container
        main_widget = QWidget()
        main_widget.setObjectName("MainWidget")
        main_widget.setStyleSheet(MAIN_STYLESHEET + """
            #MainWidget {
                border-radius: 10px;
                border: 1px solid #333333;
            }
        """)
        self.setCentralWidget(main_widget)
        
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Title Bar
        self.title_bar = TitleBar(self)
        main_layout.addWidget(self.title_bar)

        # Splitter for Sidebar and Chat Area
        self.splitter = QSplitter(Qt.Horizontal)
        
        # Sidebar
        self.sidebar = Sidebar()
        self.splitter.addWidget(self.sidebar)

        # Chat Area Container
        self.chat_container = QWidget()
        chat_layout = QVBoxLayout(self.chat_container)
        chat_layout.setContentsMargins(15, 10, 15, 15)

        # Scroll Area for Chat Bubbles
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(SCROLL_AREA_STYLESHEET)
        
        self.chat_content = QWidget()
        self.chat_content_layout = QVBoxLayout(self.chat_content)
        self.chat_content_layout.setAlignment(Qt.AlignTop)
        self.scroll_area.setWidget(self.chat_content)
        
        chat_layout.addWidget(self.scroll_area)

        # Typing Indicator
        self.typing_label = QLabel("BotBro is typing...")
        self.typing_label.setStyleSheet("color: #AAAAAA; font-style: italic; font-size: 12px;")
        self.typing_label.hide()
        chat_layout.addWidget(self.typing_label)

        # Input Area
        input_layout = QHBoxLayout()
        input_layout.setSpacing(10)
        
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Message BotBro...")
        self.text_input.setStyleSheet(INPUT_STYLESHEET)
        self.text_input.returnPressed.connect(self.handle_text_submit)
        input_layout.addWidget(self.text_input)

        self.voice_btn = QPushButton("🎤")
        self.voice_btn.setFixedSize(40, 40)
        self.voice_btn.setStyleSheet(VOICE_BTN_STYLESHEET)
        self.voice_btn.clicked.connect(self.handle_voice_click)
        input_layout.addWidget(self.voice_btn)

        chat_layout.addLayout(input_layout)

        # Status Label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #666666; font-size: 10px;")
        chat_layout.addWidget(self.status_label)

        self.splitter.addWidget(self.chat_container)
        
        # Set initial sizes for splitter
        self.splitter.setSizes([200, 600])

        main_layout.addWidget(self.splitter)

    def _append_message(self, sender: str, message: str):
        self.typing_label.hide()
        bubble = ChatBubble(sender, message)
        self.chat_content_layout.addWidget(bubble)
        
        # Auto scroll to bottom
        self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        )

    def _update_status(self, status: str):
        self.status_label.setText(status)
        if status == "Ready" or status.startswith("System"):
            self.voice_btn.setEnabled(True)
            self.text_input.setEnabled(True)
            self.typing_label.hide()
            # Stop pulse animation if any
            if hasattr(self, 'pulse_anim'):
                self.pulse_anim.stop()

    def handle_text_submit(self):
        text = self.text_input.text().strip()
        if text:
            self.text_input.clear()
            self._append_message("You", text)
            self._update_status("Processing...")
            self.typing_label.show()

            # The callback only schedules async work, so calling it directly
            # keeps the UI simple and avoids unnecessary worker threads.
            try:
                self.process_callback(text)
            except Exception as err:
                self._append_message("System Error", str(err))
                self._update_status("Ready")
                self.typing_label.hide()

    def handle_voice_click(self):
        self._update_status("Listening...")
        self.voice_btn.setEnabled(False)
        self.text_input.setEnabled(False)
        
        # Simple pulse animation on voice button
        self.pulse_anim = QPropertyAnimation(self.voice_btn, b"geometry")
        self.pulse_anim.setDuration(500)
        rect = self.voice_btn.geometry()
        self.pulse_anim.setStartValue(rect)
        self.pulse_anim.setEndValue(QRect(rect.x() - 2, rect.y() - 2, rect.width() + 4, rect.height() + 4))
        self.pulse_anim.setLoopCount(-1) # Loop infinitely until stopped
        self.pulse_anim.start()

        try:
            self.voice_callback()
        except Exception as err:
            self._append_message("System Error", str(err))
            self._update_status("Ready")
