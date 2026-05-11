"""
Centralized UI styles for the modern BotBro GUI.
"""

BACKGROUND_COLOR = "#121212"
SIDEBAR_COLOR = "#181818"
TITLEBAR_COLOR = "#1E1E1E"

USER_BUBBLE_COLOR = "#007acc"
BOT_BUBBLE_COLOR = "#2d2d2d"
TEXT_COLOR = "#EAEAEA"
MUTED_TEXT_COLOR = "#888888"
INPUT_BG_COLOR = "#1E1E1E"
ACCENT_COLOR = "#00AEEF"

MAIN_STYLESHEET = f"""
    QMainWindow {{
        background-color: {BACKGROUND_COLOR};
    }}
    QSplitter::handle {{
        background: transparent;
    }}
"""

INPUT_STYLESHEET = f"""
    QLineEdit {{
        background-color: {INPUT_BG_COLOR};
        color: {TEXT_COLOR};
        border: 1px solid #333333;
        border-radius: 18px;
        padding: 10px 15px;
        font-size: 14px;
        font-family: "Segoe UI", sans-serif;
    }}
    QLineEdit:focus {{
        border: 1px solid {ACCENT_COLOR};
    }}
"""

VOICE_BTN_STYLESHEET = f"""
    QPushButton {{
        background-color: {ACCENT_COLOR};
        color: white;
        border-radius: 18px;
        font-size: 16px;
        border: none;
    }}
    QPushButton:hover {{
        background-color: #0098ff;
    }}
    QPushButton:disabled {{
        background-color: #444444;
        color: #888888;
    }}
"""

SCROLL_AREA_STYLESHEET = f"""
    QScrollArea {{
        border: none;
        background-color: transparent;
    }}
    QScrollBar:vertical {{
        border: none;
        background: #1e1e1e;
        width: 8px;
        margin: 0px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: #555555;
        min-height: 20px;
        border-radius: 4px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        border: none;
        background: none;
    }}
"""
