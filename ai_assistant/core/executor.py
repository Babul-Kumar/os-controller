import pyautogui
import time
import os
from automation.system_control import SystemController
from automation.app_controller import AppController
from automation.file_manager import FileManager
from automation.web_automation import WebAutomator
from utils.helpers import setup_logger, json_log

logger = setup_logger(__name__)

class CommandExecutor:
    """The central Brain Router that acts on Intents."""
    def __init__(self):
        self.web_automator = WebAutomator()

    async def execute_intent(self, intent_data: dict) -> str:
        intent = intent_data.get("intent", "none")
        target = intent_data.get("target", "")

        if intent in ("none", "error", "fallback"):
            return intent_data.get("message", "⚠️ I couldn't understand that. Please try again.")

        logger.info(f"Executing intent: {intent} on target: {target}")

        try:
            if intent == "open_app":
                res = await AppController.open_app(target)
                return res.get("message", "Executed open_app")

            elif intent == "close_app":
                res = await AppController.close_app(target)
                return res.get("message", "Executed close_app")

            elif intent == "write_text":
                content = intent_data.get("content", "").strip()
                if not content:
                    return "Error: No text provided to type."

                app_target = intent_data.get("target")

                if app_target and app_target != content and app_target != "none":
                    open_res = await AppController.open_app(app_target)
                    if open_res.get("status") in ("error", "not_found", "blocked"):
                        return f"❌ Failed to open {app_target}: {open_res.get('message', 'Unknown error')}"
                        
                    # Wait up to 8 seconds for the app window to appear and receive focus
                    self._wait_for_window_focus(app_target, timeout=8)

                    # If VS Code, we must create a new file tab before typing/pasting
                    app_target_lower = app_target.lower()
                    if "code" in app_target_lower or "vscode" in app_target_lower:
                        pyautogui.hotkey("ctrl", "n")
                        time.sleep(0.5)

                self._type_text_via_clipboard(content)
                return "✅ Text written successfully"

            elif intent == "create_file":
                content = intent_data.get("content", "").strip()
                file_path = intent_data.get("target", "").strip()
                editor   = intent_data.get("editor", "").strip().lower()

                if not file_path:
                    return "❌ No filename specified."
                if not content:
                    return "❌ No content to write into the file."

                # Resolve relative paths to the user's Desktop
                if not os.path.isabs(file_path):
                    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                    file_path = os.path.join(desktop, file_path)

                # Write the file to disk
                result_msg = FileManager.create_file(file_path, content)
                logger.info(result_msg)

                # Open the file in the specified editor
                import subprocess
                editor_aliases = {
                    "vscode": "code", "vs code": "code", "visual studio code": "code",
                    "notepad": "notepad", "notepad++": "notepad++",
                }
                editor_cmd = editor_aliases.get(editor, editor or "code")

                try:
                    if editor_cmd == "code":
                        # VS Code: `code <filepath>` opens the exact file
                        subprocess.Popen(["code", file_path], shell=True)
                        time.sleep(3)  # give VS Code time to load
                    else:
                        subprocess.Popen([editor_cmd, file_path], shell=True)
                        time.sleep(2)
                except Exception as open_err:
                    logger.warning(f"Could not open editor '{editor_cmd}': {open_err}")

                return f"✅ File created at {file_path} and opened in {editor_cmd}."

            elif intent == "web_search":
                return self.web_automator.search_google(target)

            elif intent == "open_website":
                return self.web_automator.open_website(target)

            elif intent == "system_control":
                operation = intent_data.get("operation") or target
                return SystemController.execute(operation)

            elif intent == "chat_response":
                return target

            else:
                return f"Unsupported intent: {intent}"

        except Exception as e:
            logger.error(f"Execution failed for intent {intent}: {e}")
            return f"Execution error: {str(e)}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _wait_for_window_focus(self, app_name: str, timeout: int = 8):
        """Poll until the app window is visible, then activate it."""
        import pygetwindow as gw

        deadline = time.time() + timeout
        focused = False
        while time.time() < deadline:
            windows = [w for w in gw.getAllTitles() if app_name.lower() in w.lower()]
            if windows:
                try:
                    win = gw.getWindowsWithTitle(windows[0])[0]
                    win.activate()
                    focused = True
                    break
                except Exception:
                    pass
            time.sleep(0.5)

        # Extra buffer after focus so the text cursor is ready
        time.sleep(0.8 if focused else 1.5)

    def _type_text_via_clipboard(self, text: str):
        """Copy text to clipboard then paste — handles Unicode, newlines, any length."""
        try:
            import pyperclip
            pyperclip.copy(text)
            time.sleep(0.3)
            pyautogui.hotkey("ctrl", "v")
        except ImportError:
            # Graceful fallback: type character by character
            logger.warning("pyperclip not installed; falling back to character-by-character typing")
            for char in text:
                if char == "\n":
                    pyautogui.press("enter")
                else:
                    pyautogui.write(char, interval=0.02)
