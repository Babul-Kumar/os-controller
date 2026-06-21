"""
preference_learner.py — Automatically learns user preferences from command history.

Analyzes executed commands to infer:
  - Preferred IDE per file type
  - Frequently accessed folders
  - Common app sequences (e.g., Chrome → VS Code = work mode)
  - Project locations

Public API:
  - PreferenceLearner.learn_from_command(intent, target, content)
  - PreferenceLearner.analyze_history() -> dict
  - PreferenceLearner.get_user_profile_summary() -> str
  - PreferenceLearner.suggest_next_action(current_intent) -> Optional[str]
"""

import os
import json
import sqlite3
import hashlib
import datetime
from typing import Optional, Dict, List, Any, TYPE_CHECKING

from utils.helpers import setup_logger

if TYPE_CHECKING:
    from core.vector_memory import VectorMemory

logger = setup_logger(__name__)

# ── Extension → IDE mapping heuristic ────────────────────────────────────────

_EXT_EDITOR_MAP: Dict[str, str] = {
    "py":   "vscode",
    "js":   "vscode",
    "ts":   "vscode",
    "jsx":  "vscode",
    "tsx":  "vscode",
    "html": "vscode",
    "css":  "vscode",
    "json": "vscode",
    "md":   "vscode",
    "cpp":  "vscode",
    "c":    "vscode",
    "java": "vscode",
    "txt":  "notepad",
    "csv":  "notepad",
}

# Known editor keyword → canonical name
_EDITOR_CANONICAL: Dict[str, str] = {
    "vscode":  "VS Code",
    "notepad": "Notepad",
    "notepad++": "Notepad++",
    "sublime": "Sublime Text",
    "pycharm": "PyCharm",
    "idea":    "IntelliJ IDEA",
}

# Intent sequences that suggest a next action
_SEQUENCE_HINTS: Dict[str, str] = {
    "open_app:chrome":    "VS Code",
    "open_app:vscode":    "terminal",
    "create_file":        "VS Code",
    "execute_command":    "VS Code",
}


class PreferenceLearner:
    """
    Infers user preferences from executed command history and stores them
    in VectorMemory for later retrieval during prompt building.
    """

    def __init__(self, memory: "VectorMemory", db_path: str) -> None:
        """
        Args:
            memory:  VectorMemory instance used to persist learned preferences.
            db_path: Path to the SQLite database containing command_history.
        """
        self.memory  = memory
        self.db_path = db_path
        self._app_freq_cache: Dict[str, int] = {}  # in-memory frequency counter
        self._init_freq_table()

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _init_freq_table(self) -> None:
        """Ensure the app_frequency table exists."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS app_frequency (
                        app   TEXT PRIMARY KEY,
                        count INTEGER DEFAULT 0,
                        last_used TEXT
                    )
                """)
                conn.commit()
        except Exception as exc:
            logger.error("PreferenceLearner._init_freq_table failed: %s", exc)

    def _increment_app_freq(self, app_name: str) -> None:
        """Increment the usage counter for *app_name* in SQLite."""
        now = datetime.datetime.now().isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO app_frequency (app, count, last_used)
                    VALUES (?, 1, ?)
                    ON CONFLICT(app) DO UPDATE SET
                        count     = count + 1,
                        last_used = excluded.last_used
                    """,
                    (app_name.lower().strip(), now),
                )
                conn.commit()
        except Exception as exc:
            logger.error("_increment_app_freq failed: %s", exc)

    def _get_top_apps(self, limit: int = 5) -> List[str]:
        """Return the top *limit* most-used apps sorted by frequency."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT app FROM app_frequency ORDER BY count DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [r[0] for r in rows]
        except Exception as exc:
            logger.error("_get_top_apps failed: %s", exc)
            return []

    # ── Learning API ──────────────────────────────────────────────────────────

    def learn_from_command(
        self,
        intent: str,
        target: str,
        content: str = "",
    ) -> None:
        """
        Analyse a just-executed command and persist relevant preferences.

        Args:
            intent:  The resolved intent (e.g. 'create_file', 'open_app').
            target:  The target of the command (filename, app name, …).
            content: Optional content string associated with the command.
        """
        target = target or ""

        # ── Rule 1: create_file → learn preferred editor for extension ────────
        if intent == "create_file" and "." in target:
            ext = target.rsplit(".", 1)[-1].lower()
            if ext:
                pref_key = f"preferred_editor_{ext}"
                # Try to detect editor from content or default from map
                editor = _EXT_EDITOR_MAP.get(ext, "vscode")
                logger.debug(
                    "Learning preference: %s = %s (from create_file %s)",
                    pref_key, editor, target,
                )
                self.memory.learn_preference(pref_key, editor)

            # ── Rule 2: create_file → learn project folder ────────────────
            folder = os.path.dirname(os.path.abspath(target)) if os.sep in target else None
            if folder and os.path.isdir(folder):
                # Hash the folder path to produce a stable key
                folder_hash = hashlib.md5(folder.encode()).hexdigest()[:8]
                pref_key = f"known_project_{folder_hash}"
                project_name = os.path.basename(folder)
                logger.debug("Learning project: %s = %s", pref_key, project_name)
                self.memory.learn_preference(pref_key, project_name)

        # ── Rule 3: open_app → increment frequency counter ───────────────────
        elif intent == "open_app" and target:
            self._increment_app_freq(target)

    # ── Analysis API ─────────────────────────────────────────────────────────

    def analyze_history(self) -> Dict[str, Any]:
        """
        Read command_history from SQLite and return a dict of inferred
        preferences and behavioural statistics.

        Returns:
            {
                "top_apps": ["chrome", "vscode", ...],
                "editor_preferences": {"py": "vscode", ...},
                "recent_projects": ["ml-project", ...],
                "total_commands": 42,
            }
        """
        result: Dict[str, Any] = {
            "top_apps":          [],
            "editor_preferences": {},
            "recent_projects":   [],
            "total_commands":    0,
        }

        try:
            # ── Command count ─────────────────────────────────────────────────
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM command_history"
                ).fetchone()
                result["total_commands"] = row[0] if row else 0

            # ── Top apps from frequency table ─────────────────────────────────
            result["top_apps"] = self._get_top_apps()

            # ── Editor prefs & projects from VectorMemory preferences ─────────
            prefs = self.memory.get_preferences()
            editor_prefs: Dict[str, str] = {}
            recent_projects: List[str] = []

            for key, value in prefs.items():
                if key.startswith("preferred_editor_"):
                    ext = key[len("preferred_editor_"):]
                    editor_prefs[ext] = value
                elif key.startswith("known_project_"):
                    recent_projects.append(value)

            result["editor_preferences"] = editor_prefs
            result["recent_projects"]    = list(dict.fromkeys(recent_projects))[:10]

        except Exception as exc:
            logger.error("analyze_history() failed: %s", exc)

        return result

    def get_user_profile_summary(self) -> str:
        """
        Return a 3-5 line plain-text summary of the user's usage patterns
        suitable for injection into an LLM context window.

        Example::

            User preferences:
            - Preferred IDE: VS Code
            - Most opened apps: Chrome, VS Code, Notepad
            - Recent projects: ml-project, flask-app
        """
        try:
            profile = self.analyze_history()
            lines: List[str] = ["User preferences:"]

            # Dominant editor
            editor_prefs = profile.get("editor_preferences", {})
            if editor_prefs:
                # Pick the most common editor across extensions
                editor_counter: Dict[str, int] = {}
                for editor in editor_prefs.values():
                    canonical = _EDITOR_CANONICAL.get(editor.lower(), editor)
                    editor_counter[canonical] = editor_counter.get(canonical, 0) + 1
                top_editor = max(editor_counter, key=editor_counter.__getitem__)
                lines.append(f"- Preferred IDE: {top_editor}")

            # Top apps
            top_apps = profile.get("top_apps", [])
            if top_apps:
                apps_str = ", ".join(a.title() for a in top_apps[:5])
                lines.append(f"- Most opened apps: {apps_str}")

            # Recent projects
            projects = profile.get("recent_projects", [])
            if projects:
                proj_str = ", ".join(projects[:5])
                lines.append(f"- Recent projects: {proj_str}")

            return "\n".join(lines) if len(lines) > 1 else ""

        except Exception as exc:
            logger.error("get_user_profile_summary() failed: %s", exc)
            return ""

    def suggest_next_action(self, current_intent: str) -> Optional[str]:
        """
        Based on history patterns, suggest what the user might want next.

        Args:
            current_intent: The intent that was just executed.

        Returns:
            A suggestion string (e.g. 'VS Code') or None.
        """
        try:
            top_apps = self._get_top_apps(limit=3)

            # Direct sequence hint lookup
            hint = _SEQUENCE_HINTS.get(current_intent)
            if hint:
                return hint

            # App-specific sequence hints
            if current_intent == "open_app" and top_apps:
                # If Chrome is the most frequent and was just triggered, suggest vscode
                if top_apps and "chrome" in top_apps[0].lower():
                    return "VS Code"

            # If user frequently opens vscode and just executed a command → suggest terminal
            if current_intent == "execute_command":
                if any("vscode" in a.lower() or "code" in a.lower() for a in top_apps):
                    return "terminal"

            return None

        except Exception as exc:
            logger.error("suggest_next_action() failed: %s", exc)
            return None
