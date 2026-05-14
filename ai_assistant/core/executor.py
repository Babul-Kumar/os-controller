import pyautogui
import time
import os
from automation.system_control import SystemController
from automation.app_controller import AppController
from automation.file_manager import FileManager
from automation.web_automation import WebAutomator
from utils.helpers import setup_logger, json_log

logger = setup_logger(__name__)


def _coerce_text(value, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)

class CommandExecutor:
    """The central Brain Router that acts on Intents."""
    def __init__(self):
        self.web_automator = WebAutomator()

    async def execute_intent(self, intent_data: dict) -> str:
        intent = _coerce_text(intent_data.get("intent"), "none").strip() or "none"
        target = _coerce_text(intent_data.get("target", "")).strip()

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
                content = _coerce_text(intent_data.get("content", "")).strip()
                if not content:
                    return "Error: No text provided to type."

                app_target = target

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
                content = _coerce_text(intent_data.get("content", "")).strip()
                file_path = target
                editor = _coerce_text(intent_data.get("editor", "")).strip().lower()

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

            elif intent == "read_file":
                file_path = target
                if not file_path:
                    return "❌ No filename specified."
                
                if not os.path.isabs(file_path):
                    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                    file_path = os.path.join(desktop, file_path)
                    
                if not os.path.exists(file_path):
                    return f"❌ File '{file_path}' does not exist."
                    
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    return f"📄 File '{file_path}' contents:\n{content[:2000]}"
                except Exception as e:
                    return f"❌ Could not read file: {e}"

            elif intent == "modify_file":
                content = _coerce_text(intent_data.get("content", ""))
                file_path = target
                if not file_path:
                    return "❌ No filename specified."
                
                # Resolve relative paths to the user's Desktop
                if not os.path.isabs(file_path):
                    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                    file_path = os.path.join(desktop, file_path)
                
                if not os.path.exists(file_path):
                    return f"❌ File '{file_path}' does not exist."
                
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
                return f"✅ File '{file_path}' modified successfully."

            elif intent == "delete_file":
                file_path = target
                if not file_path:
                    return "❌ No filename specified."
                if not os.path.isabs(file_path):
                    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                    file_path = os.path.join(desktop, file_path)
                return FileManager.delete_file(file_path)

            elif intent == "list_directory":
                dir_path = target
                if not dir_path or dir_path.lower() in ("none", "null", "."):
                    dir_path = os.getcwd()
                elif not os.path.isabs(dir_path):
                    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                    dir_path = os.path.join(desktop, dir_path)
                
                if not os.path.exists(dir_path):
                    return f"❌ Directory '{dir_path}' does not exist."
                if not os.path.isdir(dir_path):
                    return f"❌ '{dir_path}' is not a directory."
                    
                try:
                    # Provide a simple tree-like structure for the first level
                    msg = f"📁 Directory listing for {dir_path}:\n"
                    items = os.listdir(dir_path)
                    files = []
                    dirs = []
                    for item in items:
                        full_path = os.path.join(dir_path, item)
                        if os.path.isdir(full_path):
                            dirs.append(item)
                        else:
                            files.append(item)
                    
                    dirs.sort()
                    files.sort()
                    
                    for d in dirs[:20]:
                        msg += f"  [DIR]  {d}\n"
                    if len(dirs) > 20: msg += f"  ... and {len(dirs)-20} more directories\n"
                    
                    for f in files[:30]:
                        msg += f"  [FILE] {f}\n"
                    if len(files) > 30: msg += f"  ... and {len(files)-30} more files\n"
                    return msg.strip()
                except Exception as e:
                    return f"❌ Failed to list directory: {e}"

            elif intent == "execute_command":
                import subprocess
                command = target
                if not command:
                    return "❌ No command specified."
                
                try:
                    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15)
                    output = result.stdout.strip()
                    err = result.stderr.strip()
                    if result.returncode == 0:
                        return f"✅ Command executed successfully:\n{output}"
                    else:
                        return f"❌ Command failed:\n{err or output}"
                except Exception as ex:
                    return f"❌ Command execution error: {ex}"

            elif intent == "web_search":
                return self.web_automator.search_google(target)

            elif intent == "open_website":
                return self.web_automator.open_website(target)

            elif intent == "draw_shape":
                # Ensure paint is open for drawing
                app_res = await AppController.open_app("paint")
                if app_res.get("status") in ("error", "not_found", "blocked"):
                    return f"❌ Failed to open paint: {app_res.get('message', 'Unknown error')}"
                
                self._wait_for_window_focus("paint", timeout=5)
                
                # Try to maximize the window for predictable drawing coordinates
                import pygetwindow as gw
                windows = [w for w in gw.getAllTitles() if "paint" in w.lower()]
                if windows:
                    try:
                        win = gw.getWindowsWithTitle(windows[0])[0]
                        if not win.isMaximized:
                            win.maximize()
                        time.sleep(0.5)
                    except Exception as exc:
                        logger.warning(f"Failed to maximize Paint window: {exc}")

                from automation.mouse_automation import MouseAutomator
                return MouseAutomator.draw_shape(target)

            elif intent == "system_control":
                operation = _coerce_text(intent_data.get("operation") or target).strip()
                return SystemController.execute(operation)

            elif intent == "find_file":
                from automation.file_finder import FileFinder
                results = FileFinder.find_by_name(f"*{target}*")
                if results:
                    return "✅ Found these files:\n" + "\n".join(results[:10])
                else:
                    deep = FileFinder.search_deep(f"*{target}*")
                    if deep:
                        return "✅ Found (deep search):\n" + "\n".join(deep[:10])
                    return f"❌ Could not find any file matching '{target}' on your PC."

            elif intent == "screen_info":
                from automation.screen_reader import ScreenReader
                info = ScreenReader.describe_screen()
                path = ScreenReader.take_screenshot("latest_screen.png")
                return (
                    f"👁️ Screen is {info['resolution']}, "
                    f"{'dark' if info['mode'] == 'dark' else 'light'} mode, "
                    f"brightness: {info['brightness']}/255. "
                    f"Screenshot saved to: {path}"
                )

            elif intent == "chat_response":
                return target

            else:
                return f"Unsupported intent: {intent}"

        except ModuleNotFoundError as e:
            logger.error(f"Execution failed for intent {intent}: {e}")
            missing_name = e.name or "a required package"
            return f"Missing dependency '{missing_name}'. Install the project requirements and try again."
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
