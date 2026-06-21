"""
executor.py — Central Brain Router (CommandExecutor)

Routes parsed intents to the correct automation handler. Supports all original
intents plus new Phase 1-4 capabilities:

  Phase 1: screen_click_text (OCR-find and click UI element by text)
  Phase 2: browser_task (LLM-driven Selenium web automation)
  Phase 3: (memory injected upstream in ai_service.py)
  Phase 4: multi_agent_task (planner→coder→executor→verifier pipeline)
  Bonus  : record_workflow, replay_workflow, list_workflows (Teach Botbro)

Cross-platform notes
--------------------
Intents that depend on Windows APIs (MS Paint drawing, macro recording, low-level
screen clicks, system power control) check ``os.name == 'nt'`` and return a
clear ``⚠️ Windows-only`` message when called on macOS or Linux.
"""

import os
import sys
import time
import pyautogui
from automation.system_control import SystemController
from automation.app_controller import AppController
from automation.file_manager import FileManager
from automation.web_automation import WebAutomator
from utils.helpers import setup_logger, json_log

logger = setup_logger(__name__)

_IS_WINDOWS = os.name == "nt"


def _coerce_text(value, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _windows_only_msg(intent: str) -> str:
    """Return a friendly message when a Windows-only intent is called on another OS."""
    return (
        f"⚠️ '{intent}' is only supported on Windows. "
        "This feature uses low-level Windows APIs (MS Paint, SendInput, pygetwindow) "
        "that are not available on macOS or Linux."
    )


class CommandExecutor:
    """The central Brain Router that acts on Intents."""

    def __init__(self):
        self.web_automator = WebAutomator()

        # Lazy-loaded components (initialised on first use)
        self._feedback_loop = None
        self._browser_agent = None
        self._orchestrator = None
        self._workflow_recorder = None

    # ------------------------------------------------------------------
    # Lazy loaders — keep startup fast; only import heavy deps on first use
    # ------------------------------------------------------------------

    def _get_feedback_loop(self):
        if self._feedback_loop is None:
            try:
                from automation.feedback_loop import FeedbackLoop
                self._feedback_loop = FeedbackLoop()
            except Exception as e:
                logger.warning(f"FeedbackLoop unavailable: {e}")
        return self._feedback_loop

    def _get_orchestrator(self):
        if self._orchestrator is None:
            try:
                from core.orchestrator import AgentOrchestrator
                self._orchestrator = AgentOrchestrator()
            except Exception as e:
                logger.warning(f"AgentOrchestrator unavailable: {e}")
        return self._orchestrator

    def _get_workflow_recorder(self):
        if self._workflow_recorder is None:
            try:
                from core.workflow_recorder import WorkflowRecorder
                self._workflow_recorder = WorkflowRecorder()
            except Exception as e:
                logger.warning(f"WorkflowRecorder unavailable: {e}")
        return self._workflow_recorder

    # ------------------------------------------------------------------
    # Main dispatch
    # ------------------------------------------------------------------

    async def execute_intent(self, intent_data: dict) -> str:
        intent = _coerce_text(intent_data.get("intent"), "none").strip() or "none"
        target = _coerce_text(intent_data.get("target", "")).strip()

        if intent in ("none", "error", "fallback"):
            return intent_data.get("message", "⚠️ I couldn't understand that. Please try again.")

        logger.info(f"Executing intent: {intent} on target: {target}")

        try:
            # ── Original intents ──────────────────────────────────────────

            if intent == "open_app":
                res = await AppController.open_app(target)
                msg = res.get("message", "Executed open_app")

                # Phase 1: feedback verification
                fl = self._get_feedback_loop()
                if fl and res.get("status") == "success":
                    verification = fl.verify_app_opened(target, timeout=8)
                    if not verification.success:
                        logger.warning(f"Verification failed for open_app({target}): {verification.message}")
                        msg += f" (⚠️ Window not detected after opening)"
                    else:
                        logger.info(f"Verified: {target} opened — {verification.message}")
                return msg

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

                    self._wait_for_window_focus(app_target, timeout=8)

                    app_target_lower = app_target.lower()
                    if "code" in app_target_lower or "vscode" in app_target_lower:
                        pyautogui.hotkey("ctrl", "n")
                        time.sleep(0.5)

                    # ── Focus re-verification guard ────────────────────────────────
                    # Double-check the target window is still active right before
                    # pasting, so we don't inject text into the wrong window.
                    if _IS_WINDOWS and not self._is_window_active(app_target):
                        logger.warning(
                            f"[write_text] Focus lost for '{app_target}' — re-activating."
                        )
                        self._wait_for_window_focus(app_target, timeout=4)
                    # ──────────────────────────────────────────────────────────────

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

                if not os.path.isabs(file_path):
                    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                    file_path = os.path.join(desktop, file_path)

                result_msg = FileManager.create_file(file_path, content)
                logger.info(result_msg)

                import subprocess
                editor_aliases = {
                    "vscode": "code", "vs code": "code", "visual studio code": "code",
                    "notepad": "notepad", "notepad++": "notepad++",
                }
                editor_cmd = editor_aliases.get(editor, editor or "code")

                try:
                    if editor_cmd == "code":
                        subprocess.Popen(["code", file_path], shell=True)
                        time.sleep(3)
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
                    msg = f"📁 Directory listing for {dir_path}:\n"
                    items = os.listdir(dir_path)
                    files, dirs = [], []
                    for item in items:
                        full_path = os.path.join(dir_path, item)
                        (dirs if os.path.isdir(full_path) else files).append(item)

                    dirs.sort(); files.sort()

                    for d in dirs[:20]:
                        msg += f"  [DIR]  {d}\n"
                    if len(dirs) > 20:
                        msg += f"  ... and {len(dirs)-20} more directories\n"
                    for f in files[:30]:
                        msg += f"  [FILE] {f}\n"
                    if len(files) > 30:
                        msg += f"  ... and {len(files)-30} more files\n"
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
                if not _IS_WINDOWS:
                    return _windows_only_msg("draw_shape")

                app_res = await AppController.open_app("paint")
                if app_res.get("status") in ("error", "not_found", "blocked"):
                    return "I couldn't open MS Paint. Please make sure it's installed and try again."

                self._wait_for_window_focus("paint", timeout=5)

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

            elif intent == "draw_local_image":
                if not _IS_WINDOWS:
                    return _windows_only_msg("draw_local_image")

                image_path = _coerce_text(intent_data.get("image_path", target)).strip()
                if not image_path or not os.path.exists(image_path):
                    return f"I couldn't find the image file at '{image_path}'. Please try dropping it again."

                app_res = await AppController.open_app("paint")
                if app_res.get("status") in ("error", "not_found", "blocked"):
                    return "I couldn't open MS Paint. Please make sure it's installed and try again."

                self._wait_for_window_focus("paint", timeout=5)

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

                from automation.draw_engine import draw_from_local_image
                return draw_from_local_image(image_path)

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
                path = ScreenReader.take_screenshot("latest_screen.png")

                # Determine the user's specific question
                question = intent_data.get("content") or intent_data.get("target") or "describe what is on my screen"
                if question.strip().lower() in ("screen", "none", "latest_screen.png", ""):
                    question = "describe what is on my screen"

                # Extract screen text via OCR
                ocr_text = ScreenReader.read_full_screen_text()

                if ocr_text.strip():
                    from services.ollama_service import call_ollama
                    import asyncio

                    analyze_prompt = f"""The user is looking at their desktop screen and asked: "{question}"

Below is the raw text extracted from their screen using OCR:
---
{ocr_text}
---

Please analyze the OCR text, explain what it means (particularly if there is an error, crash, warning, compiler issue, or dialog message), and suggest a practical fix or next steps."""

                    try:
                        explanation = await asyncio.get_running_loop().run_in_executor(
                            None, call_ollama, analyze_prompt
                        )
                        if explanation:
                            return f"👁️ Screen text analyzed.\n\n{explanation}"
                    except Exception as e:
                        logger.error(f"Error calling local LLM for screen analysis: {e}")

                # Fallback to simple metadata if OCR text is empty or LLM call failed
                info = ScreenReader.describe_screen()
                return (
                    f"👁️ Screen is {info['resolution']}, "
                    f"{'dark' if info['mode'] == 'dark' else 'light'} mode. "
                    f"No readable text was found on the screen via OCR. Screenshot saved to: {path}"
                )

            elif intent == "chat_response":
                return target

            # ── Phase 1: Screen OCR Click ──────────────────────────────────

            elif intent == "screen_click_text":
                """Find text on screen via OCR and click it."""
                if not _IS_WINDOWS:
                    return _windows_only_msg("screen_click_text")

                fl = self._get_feedback_loop()
                if not fl:
                    return "❌ OCR/FeedbackLoop not available. Install pytesseract to use screen clicking."

                location = fl.find_text_on_screen(target)
                if location:
                    x, y = location
                    pyautogui.click(x, y)
                    time.sleep(0.3)
                    return f"✅ Clicked on '{target}' at screen position ({x}, {y})."
                else:
                    return f"❌ Could not find '{target}' on screen. Make sure it's visible and try again."

            # ── Phase 2: Browser Agent ────────────────────────────────────

            elif intent == "browser_task":
                """LLM-driven Selenium web automation."""
                try:
                    result = self.web_automator.execute_web_task(target)
                    return result
                except Exception as e:
                    logger.error(f"Browser task failed: {e}")
                    return f"❌ Browser task failed: {e}"

            # ── Phase 4: Multi-Agent Orchestration ───────────────────────

            elif intent == "multi_agent_task":
                """Execute a complex multi-step task using the agent pipeline."""
                orchestrator = self._get_orchestrator()
                if not orchestrator:
                    return "❌ Multi-agent system unavailable. Check that all agent modules are installed."

                return await orchestrator.run_complex_task(target)

            # ── Teach Botbro: Workflow Recording ─────────────────────────

            elif intent == "record_workflow":
                if not _IS_WINDOWS:
                    return _windows_only_msg("record_workflow")

                recorder = self._get_workflow_recorder()
                if not recorder:
                    return "❌ Workflow recorder unavailable. Install pynput: pip install pynput"

                workflow_name = _coerce_text(intent_data.get("content", target or "my_workflow"))
                result = recorder.start_recording()
                self._current_recording_name = workflow_name
                return f"🔴 {result}\n💡 Tip: Say 'stop recording' when done."

            elif intent == "stop_recording":
                if not _IS_WINDOWS:
                    return _windows_only_msg("stop_recording")

                recorder = self._get_workflow_recorder()
                if not recorder:
                    return "❌ Workflow recorder unavailable."

                stop_msg = recorder.stop_recording()
                name = getattr(self, "_current_recording_name", "my_workflow")
                save_msg = recorder.save_workflow(name)
                return f"⏹️ {stop_msg}\n💾 {save_msg}"

            elif intent == "replay_workflow":
                if not _IS_WINDOWS:
                    return _windows_only_msg("replay_workflow")

                recorder = self._get_workflow_recorder()
                if not recorder:
                    return "❌ Workflow recorder unavailable."

                return recorder.replay_workflow(target)

            elif intent == "list_workflows":
                recorder = self._get_workflow_recorder()
                if not recorder:
                    return "❌ Workflow recorder unavailable."

                workflows = recorder.list_workflows()
                if workflows:
                    return "📋 Saved workflows:\n" + "\n".join(f"  • {w}" for w in workflows)
                return "📭 No workflows saved yet. Say 'start recording' to create one."

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

    def _is_window_active(self, app_name: str) -> bool:
        """Return True when the currently-focused window title contains *app_name*.

        Uses pygetwindow to inspect the active window.  Returns True on any
        error (optimistic — better to proceed than to block unnecessarily).
        """
        try:
            import pygetwindow as gw
            active = gw.getActiveWindow()
            if active is None:
                return False
            return app_name.lower() in (active.title or "").lower()
        except Exception as exc:
            logger.debug(f"[_is_window_active] check failed: {exc}")
            return True  # optimistic fallback

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

        time.sleep(0.8 if focused else 1.5)

    def _type_text_via_clipboard(self, text: str):
        """Copy text to clipboard then paste — handles Unicode, newlines, any length."""
        try:
            import pyperclip
            pyperclip.copy(text)
            time.sleep(0.3)
            pyautogui.hotkey("ctrl", "v")
        except ImportError:
            logger.warning("pyperclip not installed; falling back to character-by-character typing")
            for char in text:
                if char == "\n":
                    pyautogui.press("enter")
                else:
                    pyautogui.write(char, interval=0.02)
