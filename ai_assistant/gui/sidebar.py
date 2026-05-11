from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import Qt
from gui.styles import SIDEBAR_COLOR

class Sidebar(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.setMinimumWidth(200)
        self.setMaximumWidth(300)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {SIDEBAR_COLOR};
                border-bottom-left-radius: 10px;
            }}
        """)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 20, 15, 20)
        layout.setSpacing(15)

        # Title
        title = QLabel("BotBro Settings")
        title.setStyleSheet("color: #FFFFFF; font-size: 16px; font-weight: bold; font-family: 'Segoe UI';")
        layout.addWidget(title)

        # Nav items
        nav_items = ["Chat History", "Memory Logs", "Plugins", "Settings"]
        for item in nav_items:
            btn = QPushButton(item)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #AAAAAA;
                    text-align: left;
                    padding: 8px;
                    border-radius: 5px;
                    font-size: 14px;
                    border: none;
                }
                QPushButton:hover {
                    background-color: #2A2A2A;
                    color: #FFFFFF;
                }
            """)
            layout.addWidget(btn)

        layout.addStretch()

        # Status or Info at bottom
        info_label = QLabel("v1.0.0")
        info_label.setStyleSheet("color: #555555; font-size: 10px;")
        layout.addWidget(info_label)

        self.setLayout(layout)
