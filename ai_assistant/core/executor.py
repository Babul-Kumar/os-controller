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
import ast
import difflib
import tempfile
import pyautogui
from config.settings import PENDING_CHANGE_TIMEOUT
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

    def __init__(self, cache_manager=None):
        self.web_automator = WebAutomator()

        if cache_manager is None:
            import os
            from core.code_intelligence.cache_manager import CacheManager
            workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.cache_manager = CacheManager(workspace_dir)
            self.cache_manager.load_or_rebuild_index()
        else:
            self.cache_manager = cache_manager

        # Lazy-loaded components (initialised on first use)
        self._feedback_loop = None
        self._browser_agent = None
        self._orchestrator = None
        self._workflow_recorder = None
        self.pending_change = None

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

                # Avoid concurrent changes
                if getattr(self, "pending_change", None):
                    # Expire old changes first
                    if time.time() - self.pending_change["created_at"] > PENDING_CHANGE_TIMEOUT:
                        self.pending_change = None
                    else:
                        return "⚠️ You already have an active pending change. Please 'apply' or 'cancel' it before staging new changes."

                # Resolve file path
                if not os.path.isabs(file_path):
                    workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    
                    # If it's a plain filename without directory components, search recursively
                    if "/" not in file_path.replace("\\", "/"):
                        matching_paths = []
                        for root, dirs, files in os.walk(workspace_dir):
                            from config.settings import IGNORED_DIRS
                            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
                            if file_path in files:
                                matching_paths.append(os.path.join(root, file_path))

                        if len(matching_paths) > 1:
                            options_list = []
                            for p in matching_paths:
                                rel = os.path.relpath(p, workspace_dir)
                                rel_norm = rel.replace("\\\\", "/").replace("\\", "/")
                                options_list.append(f"- `{rel_norm}`")
                            options = "\n".join(options_list)
                            return (
                                f"⚠️ **Ambiguity Detected**: Multiple files match the name '{file_path}':\n"
                                f"{options}\n\n"
                                f"Please specify the relative path to clarify which file you wish to modify."
                            )
                        elif len(matching_paths) == 1:
                            file_path = matching_paths[0]
                        else:
                            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                            file_path = os.path.join(desktop, file_path)
                    else:
                        # It is a specific relative path (e.g. "src/main.py")
                        possible_path = os.path.join(workspace_dir, file_path)
                        if os.path.exists(possible_path):
                            file_path = possible_path
                        else:
                            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                            file_path = os.path.join(desktop, file_path)

                if not os.path.exists(file_path):
                    return f"❌ File '{file_path}' does not exist."

                # Read existing contents
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        old_content = f.read()
                except Exception as e:
                    return f"❌ Could not read original file '{file_path}': {e}"

                # Syntax validation for python files
                if file_path.endswith(".py"):
                    try:
                        ast.parse(content)
                    except SyntaxError as exc:
                        return f"❌ Syntax check failed for proposed changes in '{os.path.basename(file_path)}':\n[Line {exc.lineno}] {exc.msg}\n\nModification was rejected."

                # Compute unified diff
                old_lines = old_content.splitlines(keepends=True)
                new_lines = content.splitlines(keepends=True)
                diff_lines = list(difflib.unified_diff(
                    old_lines, new_lines,
                    fromfile=f"a/{os.path.basename(file_path)}",
                    tofile=f"b/{os.path.basename(file_path)}"
                ))
                diff_text = "".join(diff_lines)

                if not diff_text.strip():
                    return f"📝 Proposed changes match existing content of '{os.path.basename(file_path)}' exactly. No modification staged."

                # Stage in memory
                workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                rel_path = os.path.relpath(file_path, workspace_dir)

                self.pending_change = {
                    "file_path": file_path,
                    "old_content": old_content,
                    "new_content": content,
                    "diff": diff_text,
                    "created_at": time.time()
                }

                return (
                    f"🔍 **Proposed Changes for `{rel_path}`**:\n\n"
                    f"```diff\n{diff_text}\n```\n\n"
                    f"💡 Say **'yes'** / **'apply'** to commit, or **'cancel'** / **'no'** to discard."
                )

            elif intent == "show_pending_change":
                change = getattr(self, "pending_change", None)
                if not change:
                    return "ℹ️ You do not have any pending changes staged."

                # Verify expiration
                if time.time() - change["created_at"] > PENDING_CHANGE_TIMEOUT:
                    self.pending_change = None
                    return "⚠️ Staged change has expired (5-minute timeout). Please re-request the code modification."

                workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                rel_path = os.path.relpath(change["file_path"], workspace_dir)
                return (
                    f"🔍 **Current Staged Changes for `{rel_path}`**:\n\n"
                    f"```diff\n{change['diff']}\n```\n\n"
                    f"💡 Say **'yes'** / **'apply'** to commit, or **'cancel'** / **'no'** to discard."
                )

            elif intent == "explain_code":
                question = intent_data.get("content") or f"Explain code context for {target}"
                from services.ollama_service import call_ollama
                import asyncio

                explain_prompt = f"""You are a helpful local AI coding agent. The user is asking a question:
"{question}"

Please provide a clear and detailed explanation of the code, functions, or files. Focus on clarity and detail."""
                try:
                    explanation = await asyncio.get_running_loop().run_in_executor(
                        None, call_ollama, explain_prompt
                    )
                    return explanation or "I couldn't generate an explanation. Let me know how else I can help."
                except Exception as e:
                    return f"❌ Failed to explain code: {e}"

            elif intent == "review_code":
                question = intent_data.get("content") or f"Review code file {target}"
                from services.ollama_service import call_ollama
                import asyncio

                review_prompt = f"""You are an expert local AI code reviewer. The user is asking:
"{question}"

Please review the code file, identify any potential bugs, safety issues, performance bottlenecks, or code smell, and suggest improvements or refactoring options."""
                try:
                    review = await asyncio.get_running_loop().run_in_executor(
                        None, call_ollama, review_prompt
                    )
                    return review or "I couldn't generate a code review."
                except Exception as e:
                    return f"❌ Failed to review code: {e}"


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
                # Special check for confirmation if there's a pending change
                confirm_words = {"yes", "apply", "proceed", "do it", "y"}
                cancel_words = {"no", "cancel", "stop", "n"}
                cleaned_target = target.strip().lower().rstrip("!.")

                change = getattr(self, "pending_change", None)
                if change:
                    if cleaned_target in confirm_words:
                        # Check expiration
                        if time.time() - change["created_at"] > PENDING_CHANGE_TIMEOUT:
                            self.pending_change = None
                            return "⚠️ Staged change has expired (5-minute timeout). Please re-request the code modification."

                        file_path = change["file_path"]
                        # Create backup
                        backup_path = file_path + ".botbro.bak"
                        try:
                            with open(backup_path, "w", encoding="utf-8") as bf:
                                bf.write(change["old_content"])
                        except Exception as e:
                            logger.warning(f"Failed to create backup for {file_path}: {e}")

                        # Atomic write
                        try:
                            dir_name = os.path.dirname(file_path)
                            base_name = os.path.basename(file_path)
                            with tempfile.NamedTemporaryFile(
                                "w", dir=dir_name, prefix=f".tmp_{base_name}", delete=False, encoding="utf-8"
                            ) as tf:
                                tf.write(change["new_content"])
                                tf.flush()
                                os.fsync(tf.fileno())
                                temp_path = tf.name

                            os.replace(temp_path, file_path)
                            self.pending_change = None
                            return f"✅ Applied changes to '{os.path.basename(file_path)}' successfully! Backup saved to: {os.path.basename(backup_path)}"
                        except Exception as e:
                            return f"❌ Failed to commit changes atomically: {e}"

                    elif cleaned_target in cancel_words:
                        self.pending_change = None
                        return "❌ Staged changes discarded successfully."

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

            elif intent == "find_symbol":
                symbol_name = target or intent_data.get("content")
                if not symbol_name:
                    return "❌ Please specify a symbol name to find."
                from core.code_intelligence.search_engine import SearchEngine
                results = SearchEngine.symbol_lookup(self.cache_manager.code_index, symbol_name)
                if not results:
                    results = SearchEngine.keyword_search(self.cache_manager.code_index, symbol_name)
                if not results:
                    return f"🔍 No symbols found matching '{symbol_name}'."
                
                msg = f"🔍 Found {len(results)} symbols matching '{symbol_name}':\n\n"
                for r in results[:5]:
                    msg += f"• **{r['name']}** ({r['type']}) in `{r['file_path']}` (Lines {r['start_line']}-{r['end_line']})\n"
                    if r.get("docstring"):
                        msg += f"  *Docstring:* {r['docstring'].strip()}\n"
                    if r.get("snippet"):
                        snip_lines = r['snippet'].splitlines()
                        snip_preview = "\n".join(snip_lines[:10])
                        if len(snip_lines) > 10:
                            snip_preview += "\n..."
                        msg += f"  ```python\n{snip_preview}\n  ```\n"
                return msg

            elif intent == "find_references":
                symbol_name = target or intent_data.get("content")
                if not symbol_name:
                    return "❌ Please specify a symbol name to find references for."
                from core.code_intelligence.search_engine import SearchEngine
                sym_results = SearchEngine.symbol_lookup(self.cache_manager.code_index, symbol_name)
                if not sym_results:
                    return f"🔍 No symbols found matching '{symbol_name}' to look up references."
                
                symbol_id = sym_results[0]["id"]
                refs = SearchEngine.reference_lookup(self.cache_manager.reference_index, symbol_id)
                if not refs:
                    return f"🔍 No references found for symbol '{symbol_id}'."
                
                msg = f"🔍 Found {len(refs)} references for symbol `{symbol_id}`:\n\n"
                for ref in refs:
                    msg += f"• `{ref['file_path']}` at Line {ref['line_no']}\n"
                return msg

            elif intent == "trace_execution":
                start_symbol = target or intent_data.get("content")
                if not start_symbol:
                    return "❌ Please specify a start symbol to trace."
                call_graph = {}
                from core.code_intelligence.call_graph import CallGraphExtractor
                for rel_path in self.cache_manager.file_summaries.keys():
                    if rel_path.endswith(".py"):
                        local_calls = CallGraphExtractor.extract_calls_from_file(self.cache_manager.workspace_dir, rel_path)
                        for ctx, calls in local_calls.items():
                            if ctx not in call_graph:
                                call_graph[ctx] = []
                            for c in calls:
                                if c not in call_graph[ctx]:
                                    call_graph[ctx].append(c)
                
                trace = CallGraphExtractor.trace_execution_flow(call_graph, start_symbol)
                if not trace:
                    return f"🔍 No execution trace found starting from '{start_symbol}'."
                return f"🕸️ **Execution Trace for `{start_symbol}`**:\n" + "\n".join(trace)

            elif intent == "list_symbols":
                file_path = target or intent_data.get("content")
                if not file_path:
                    return "❌ Please specify a file path to list symbols."
                norm_path = file_path.replace("\\", "/")
                matching_files = [f for f in self.cache_manager.file_summaries.keys() if norm_path in f]
                if not matching_files:
                    return f"❌ File '{file_path}' not found in the index."
                
                selected_file = matching_files[0]
                file_symbols = []
                for sym_id, info in self.cache_manager.code_index.items():
                    if info["file_path"] == selected_file:
                        file_symbols.append(info)
                        
                if not file_symbols:
                    return f"📁 No symbols found in '{selected_file}'."
                
                msg = f"📁 Symbols defined in `{selected_file}`:\n\n"
                for s in sorted(file_symbols, key=lambda x: x["start_line"]):
                    parent_str = f" (in class {s['parent']})" if s.get("parent") else ""
                    msg += f"• **{s['name']}** ({s['type']}){parent_str} on Lines {s['start_line']}-{s['end_line']}\n"
                return msg

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
