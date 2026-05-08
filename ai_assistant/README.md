# Botbro AI Desktop Assistant

A complete, production-ready AI desktop assistant built with a robust decoupled architecture. Botbro uses local AI (Ollama) to guarantee privacy, reliability, and execution speed.

## 🌟 Key Features

- **Decoupled Service Architecture**: Clean separation between `GUI`, `Services`, `Core`, and `Automation`.
- **Intelligent Engine**:
  - **Primary**: Local Ollama Model (`llama3`).
  - **Fallback**: Naive offline rule-based parser.
- **Content Generation Pipeline**: Not just app opening! Ask Botbro to *"write an essay on friendship in notepad"* and it will launch the app and type the content autonomously.
- **Fuzzy Matching Integration**: Utilizes high-performance `rapidfuzz` to correct typos instantly (e.g., "esay" -> "essay", "chrom" -> "chrome").
- **Voice Feedback**: Spoken feedback using `pyttsx3`.
- **OS Automation**: Deep integrations for OS-level control, web searching, and file management via `pyautogui`, `pygetwindow`, and `psutil`.

## 📂 Architecture Overview

- `main.py` - Async event loop and PyQt5 GUI bridge.
- `services/` - AI dispatch routing (`ai_service.py`, `ollama_service.py`).
- `core/` - Brain logic (`executor.py`), Strict JSON Parsing (`command_parser.py`), Database (`memory.py`), and Safety Permissions (`security.py`).
- `automation/` - The physical hands (`app_controller.py`, `web_automation.py`, `system_control.py`).

## 🚀 Setup Instructions

1. **Install Python Dependencies**
   Ensure you are using your virtual environment and install the required modules:
   ```bash
   pip install pygetwindow psutil pyautogui PyQt5 rapidfuzz ollama
   ```

2. **Install Local AI (Ollama)**
   Install [Ollama](https://ollama.com/) and download the required model:
   ```bash
   ollama pull llama3
   ```

3. **Run Botbro**
   ```bash
   python main.py
   ```

## 🧠 Example Commands to Try

- **Content Generation**: "Write an essay about AI in Notepad"
- **App Control**: "Open Chrome" or "Close Calculator"
- **Fuzzy Corrections**: "Open notpad" (Botbro will know you meant Notepad)
- **Web Browsing**: "Open youtube"
- **System**: "Lock the workstation"

## 📦 Building the EXE (Packaging)

To package this application into a standalone executable:

1. Install PyInstaller:
   ```bash
   pip install pyinstaller
   ```

2. Run PyInstaller from the `ai_assistant` directory:
   ```bash
   pyinstaller --onefile --windowed --name="Botbro" main.py
   ```
   
   **Note**: If PyInstaller complains about missing hidden imports, explicitly include them:
   `pyinstaller --onefile --windowed --hidden-import="ollama" --hidden-import="rapidfuzz" --name="Botbro" main.py`
