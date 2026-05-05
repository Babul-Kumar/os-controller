import sys
import threading
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, 
    QHBoxLayout, QTextEdit, QLineEdit, QPushButton, QLabel
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor, QPalette

from config.settings import APP_NAME, VERSION

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
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.setFixedSize(600, 800)
        
        # Dark Theme Palette
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(30, 30, 30))
        palette.setColor(QPalette.WindowText, Qt.white)
        self.setPalette(palette)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # Chat History
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setStyleSheet("""
            QTextEdit {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #3d3d3d;
                border-radius: 5px;
                padding: 10px;
                font-size: 14px;
            }
        """)
        layout.addWidget(self.chat_display)

        # Status Label
        self.status_label = QLabel("Status: Ready")
        self.status_label.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        layout.addWidget(self.status_label)

        # Input Area
        input_layout = QHBoxLayout()
        
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Type a command...")
        self.text_input.setStyleSheet("""
            QLineEdit {
                background-color: #3b3b3b;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 15px;
                padding: 8px 15px;
                font-size: 14px;
            }
        """)
        self.text_input.returnPressed.connect(self.handle_text_submit)
        input_layout.addWidget(self.text_input)

        self.voice_btn = QPushButton("🎤")
        self.voice_btn.setFixedSize(40, 40)
        self.voice_btn.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                border-radius: 20px;
                font-size: 18px;
            }
            QPushButton:hover {
                background-color: #0098ff;
            }
        """)
        self.voice_btn.clicked.connect(self.handle_voice_click)
        input_layout.addWidget(self.voice_btn)

        layout.addLayout(input_layout)

    def _append_message(self, sender: str, message: str):
        color = "#00aaff" if sender == "You" else "#4caf50"
        html = f'<b><font color="{color}">{sender}:</font></b> <font color="white">{message}</font><br>'
        self.chat_display.append(html)
        # Scroll to bottom
        scrollbar = self.chat_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _update_status(self, status: str):
        self.status_label.setText(f"Status: {status}")

    def handle_text_submit(self):
        text = self.text_input.text().strip()
        if text:
            self.text_input.clear()
            self._update_status("Processing...")
            self._append_message("You", text)
            
            # Run processing in a separate thread so UI doesn't freeze
            threading.Thread(target=self.process_callback, args=(text,), daemon=True).start()

    def handle_voice_click(self):
        self._update_status("Listening...")
        self.voice_btn.setEnabled(False)
        self.text_input.setEnabled(False)
        
        # Run voice recognition in a separate thread
        threading.Thread(target=self.voice_callback, daemon=True).start()
