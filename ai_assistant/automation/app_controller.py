import os
import re
import asyncio
import subprocess
import winreg
import psutil
from typing import List, Dict, Any, Optional, Tuple

import pygetwindow as gw
from utils.helpers import setup_logger, json_log, fuzzy_match, get_close_suggestions
from core.security import validate_shell_command

logger = setup_logger(__name__)

class AppController:
    # -------------------------------------------------------------
    #   Static configuration (paths, aliases, verbs,…)
    # -------------------------------------------------------------
    COMMON_APPS = {
        "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "explorer": "explorer.exe",
        "paint": "mspaint.exe",
        "powerpoint": "powerpnt.exe",
        "word": "winword.exe",
        "excel": "excel.exe",
        "vscode": "code.cmd",
        # “start” protocols – they are launched via the shell
        "camera": "start microsoft.windows.camera:",
        "settings": "start ms-settings:",
        "mail": "start outlookmail:",
        "calendar": "start outlookcal:",
        "whatsapp": "start whatsapp:",
        "whatsapp web": "start https://web.whatsapp.com",
        "youtube": "start https://youtube.com",
    }

    APP_ALIASES = {
        "text editor": "notepad",
        "notes": "notepad",
        "browser": "chrome",
        "internet": "chrome",
        "web": "chrome",
        "calc": "calculator",
        "painting": "paint",
        "photo editor": "paint",
        "camera app": "camera",
        "settings app": "settings",
        "visual studio code": "vscode",
        "vs code": "vscode",
        "vscode": "vscode",
        "powerpoint": "powerpoint",
        "power pnt": "powerpoint",
        "ms word": "word",
        "microsoft word": "word",
        "word document": "word",
        "ms excel": "excel",
        "microsoft excel": "excel",
    }

    _app_path_cache: Dict[str, Optional[str]] = {}

    APP_PERMISSIONS = {
        "chrome": "safe",
        "notepad": "safe",
        "calculator": "safe",
        "explorer": "safe",
        "paint": "safe",
        "cmd": "safe",
        "powershell": "safe",
    }

    LAST_APP: Optional[str] = None
    ACTIVE_PROCESSES: Dict[int, Dict[str, Any]] = {}

    @staticmethod
    def normalize_name(name: str) -> str:
        return os.path.splitext(name.lower())[0]

    @classmethod
    def _validate_command(cls, cmd: str) -> Tuple[bool, Optional[str]]:
        """
        In safe‑mode we reject any command that contains shell‑control characters.
        Returns (allowed, reason_if_blocked).
        """
        return validate_shell_command(cmd)

    @classmethod
    def _resolve_executable(cls, canonical: str) -> Optional[str]:
        if canonical in cls._app_path_cache:
            return cls._app_path_cache[canonical]

        if canonical in cls.COMMON_APPS:
            result = cls.COMMON_APPS[canonical]
            cls._app_path_cache[canonical] = result
            return result

        reg_path = cls._find_app_in_registry(canonical)
        if reg_path:
            cls._app_path_cache[canonical] = reg_path
            return reg_path

        import shutil
        which_path = shutil.which(canonical)
        if which_path:
            cls._app_path_cache[canonical] = which_path
            return which_path

        cls._app_path_cache[canonical] = None
        return None

    @staticmethod
    def _find_app_in_registry(app_name: str) -> Optional[str]:
        search_keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths")
        ]
        for root, sub_key in search_keys:
            try:
                with winreg.OpenKey(root, sub_key) as base_key:
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(base_key, i)
                        except OSError:
                            break
                        i += 1
                        if AppController.normalize_name(app_name) in AppController.normalize_name(subkey_name):
                            with winreg.OpenKey(base_key, subkey_name) as subkey:
                                path, _ = winreg.QueryValueEx(subkey, "")
                                if os.path.isfile(path):
                                    return path
            except FileNotFoundError:
                continue
        return None

    @classmethod
    def is_running(cls, app_name: str) -> bool:
        target = cls.normalize_name(app_name)
        for proc in psutil.process_iter(['name']):
            if proc.info['name'] and cls.normalize_name(proc.info['name']) == target:
                return True
        return False

    @staticmethod
    def _window_action(app_name: str, method: str) -> dict:
        matches = [w for w in gw.getAllTitles() if app_name.lower() in w.lower()]
        if not matches:
            json_log(logger, "window_action", app=app_name, method=method, status="not_found")
            return {"status": "not_found", "message": f"⚠️ No window matches '{app_name}'."}
        try:
            win = gw.getWindowsWithTitle(matches[0])[0]
            getattr(win, method)()
            json_log(logger, "window_action", app=app_name, method=method, status="success")
            return {"status": "success", "message": f"✅ {method.capitalize()}ed '{app_name}'."}
        except Exception as exc:
            json_log(logger, "window_action", app=app_name, method=method, status="error", error=str(exc))
            return {"status": "error", "message": f"❌ Failed to {method} '{app_name}'."}

    @classmethod
    def focus_app(cls, app_name: str) -> dict:
        return cls._window_action(app_name, "activate")

    @classmethod
    async def open_app(cls, app_name: str) -> dict:
        raw = app_name.strip()
        logger.info(f"[OPEN] Request: {raw}")

        lc = raw.lower()
        canonical = cls.APP_ALIASES.get(lc, lc)
        
        # 1. Try to resolve directly
        cmd = cls._resolve_executable(canonical)
        
        # 2. If not found, try fuzzy match
        if not cmd:
            all_keys = list(cls.COMMON_APPS.keys()) + list(cls.APP_ALIASES.keys())
            matched = fuzzy_match(canonical, all_keys)
            if matched:
                canonical = matched
                cmd = cls._resolve_executable(canonical)
            else:
                suggestions = get_close_suggestions(canonical, all_keys)
                if suggestions:
                    return {"status": "not_found", "message": f"❌ Could not find '{raw}'. Did you mean: {', '.join(suggestions)}?"}
                else:
                    cmd = raw # fallback

        perm = cls.APP_PERMISSIONS.get(canonical, "safe")
        if perm == "restricted":
            json_log(logger, "open", app=canonical, status="blocked")
            return {"status": "blocked", "message": f"🚫 {canonical} is a restricted app."}

        if cls.is_running(canonical):
            focused = cls.focus_app(raw)
            note = " (focused)" if focused["status"] == "success" else ""
            json_log(logger, "open", app=canonical, status="already_running")
            return {"status": "already_running", "message": f"⚡ {raw} is already running{note}."}

        allowed, reason = cls._validate_command(cmd)
        if not allowed:
            json_log(logger, "open", app=canonical, status="blocked", reason=reason)
            return {"status": "blocked", "message": f"🚫 Blocked: {reason}"}

        loop = asyncio.get_running_loop()

        def _launch() -> subprocess.Popen:
            if cmd.strip().lower().startswith("start "):
                return subprocess.Popen(cmd, shell=True)
            return subprocess.Popen(cmd, shell=False)

        try:
            proc = await loop.run_in_executor(None, _launch)
            pid = proc.pid
            cls.LAST_APP = canonical
            json_log(logger, "open", app=canonical, pid=pid, status="success")
            return {"status": "success", "pid": pid, "message": f"✅ {raw} launched successfully."}
        except FileNotFoundError:
            json_log(logger, "open", app=canonical, status="not_found")
            return {"status": "not_found", "message": f"❌ Could not find '{raw}'."}
        except Exception as exc:
            json_log(logger, "open", app=canonical, status="error", error=str(exc))
            return {"status": "error", "message": f"❌ Unexpected error: {exc}"}

    @classmethod
    async def close_app(cls, app_name: str) -> dict:
        raw = app_name.strip()
        logger.info(f"[CLOSE] Request: {raw}")

        lc = raw.lower()
        canonical = cls.APP_ALIASES.get(lc, lc)
        all_keys = list(cls.COMMON_APPS.keys()) + list(cls.APP_ALIASES.keys())
        matched = fuzzy_match(canonical, all_keys)
        if matched:
            canonical = matched

        target_norm = cls.normalize_name(canonical)
        closed = 0

        for proc in psutil.process_iter(['name']):
            name = proc.info['name']
            if not name:
                continue
            if cls.normalize_name(name) == target_norm:
                try:
                    proc.terminate()
                    closed += 1
                except Exception:
                    pass

        if closed:
            json_log(logger, "close", app=canonical, closed=closed, status="success")
            return {"status": "closed", "message": f"✅ Closed {closed} instance(s) of {raw}."}
        else:
            json_log(logger, "close", app=canonical, status="not_found")
            return {"status": "not_found", "message": f"⚠️ No running instance of {raw} found."}
