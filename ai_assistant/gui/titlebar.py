from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import Qt, QPoint
from gui.styles import TITLEBAR_COLOR

class TitleBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.init_ui()
        self.start_pos = None

    def init_ui(self):
        self.setFixedHeight(38)
        self.setStyleSheet(
            "background-color: #09090f;"
            "border-top-left-radius: 12px;"
            "border-top-right-radius: 12px;"
            "border-bottom: 1px solid #1a1a2e;"
        )

        layout = QHBoxLayout()
        layout.setContentsMargins(14, 0, 10, 0)
        layout.setSpacing(6)

        # Status dot + title
        dot = QLabel("●")
        dot.setStyleSheet("color: #00AEEF; font-size: 10px;")
        layout.addWidget(dot)

        self.title_label = QLabel("BotBro AI  —  Future")
        self.title_label.setStyleSheet(
            "color: #6677aa; font-weight: 600; "
            "font-family: 'Segoe UI', sans-serif; font-size: 12px;"
        )
        layout.addWidget(self.title_label)

        layout.addStretch()

        # Minimize Button
        self.min_btn = QPushButton("—")
        self.min_btn.setFixedSize(30, 30)
        self.min_btn.setStyleSheet(self._btn_style())
        self.min_btn.clicked.connect(self.parent_window.showMinimized)
        layout.addWidget(self.min_btn)

        # Maximize Button
        self.max_btn = QPushButton("□")
        self.max_btn.setFixedSize(30, 30)
        self.max_btn.setStyleSheet(self._btn_style())
        self.max_btn.clicked.connect(self.toggle_maximize)
        layout.addWidget(self.max_btn)

        # Close Button
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setStyleSheet(self._btn_style(hover_color="#E81123"))
        self.close_btn.clicked.connect(self.parent_window.close)
        layout.addWidget(self.close_btn)

        self.setLayout(layout)

    def _btn_style(self, hover_color="#444444"):
        return f"""
            QPushButton {{
                background-color: transparent;
                color: #CCCCCC;
                border: none;
                font-size: 14px;
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
                color: white;
            }}
        """

    def toggle_maximize(self):
        if self.parent_window.isMaximized():
            self.parent_window.showNormal()
            self.max_btn.setText("□")
        else:
            self.parent_window.showMaximized()
            self.max_btn.setText("❐")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_pos = event.globalPos()

    def mouseMoveEvent(self, event):
        if self.start_pos:
            delta = event.globalPos() - self.start_pos
            self.parent_window.move(self.parent_window.pos() + delta)
            self.start_pos = event.globalPos()

    def mouseReleaseEvent(self, event):
        self.start_pos = None
