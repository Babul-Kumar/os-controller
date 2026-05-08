import re
import asyncio
from typing import Dict, Any, Optional
from utils.helpers import setup_logger, json_log
from core.command_parser import CommandParser
from core.memory import MemoryManager
from services.ollama_service import call_ollama

logger = setup_logger(__name__)

# Apps that Botbro can type into
_WRITABLE_APPS = {"notepad", "wordpad", "word", "microsoft word", "notepad++", "sublime", "vscode"}

# Verbs that signal a write_text intent
_WRITE_VERBS = re.compile(
    r"\b(write|type|compose|draft|create|prepare|make)\b", re.IGNORECASE
)

# Verbs that signal file creation specifically
_FILE_VERBS = re.compile(
    r"\b(make a file|create a file|create file|make file|new file|write a file)\b", re.IGNORECASE
)

# Extension pattern to detect a filename in the command
_FILENAME_RE = re.compile(r"\b([\w\-]+\.(?:py|txt|js|ts|html|css|java|cpp|c|json|csv|md))\b", re.IGNORECASE)

# Editor keywords
_EDITOR_KEYWORDS = {
    "vscode": "vscode", "vs code": "vscode", "visual studio code": "vscode",
    "notepad": "notepad", "notepad++": "notepad++", "sublime": "sublime",
}


def _detect_create_file_intent_locally(text: str):
    """Return a create_file intent dict if the user wants to make a new file, else None."""
    tl = text.lower()
    if not _FILE_VERBS.search(tl):
        return None
    filename_match = _FILENAME_RE.search(text)
    if not filename_match:
        return None
    filename = filename_match.group(1)
    editor = "vscode"  # default
    for kw, name in _EDITOR_KEYWORDS.items():
        if kw in tl:
            editor = name
            break
    return {"intent": "create_file", "target": filename, "editor": editor, "content": "", "confidence": 0.6}


def _detect_write_intent_locally(text: str):
    """
    Local heuristic: if the command contains a write verb AND a known writable
    app name, return a write_text intent with a placeholder content so the
    executor knows to generate the text.  The actual content comes from Ollama;
    this is only used when Ollama mis-classifies.
    """
    tl = text.lower()
    if not _WRITE_VERBS.search(tl):
        return None
    for app in _WRITABLE_APPS:
        if app in tl:
            return {"intent": "write_text", "target": app, "content": "", "confidence": 0.6}
    return None


class AIService:
    def __init__(self):
        self.memory = MemoryManager()
        json_log(logger, "ai_service", status="configured_ollama_only")

    async def process_intent(self, user_text: str) -> Dict[str, Any]:
        """Send input to Ollama, get JSON string, parse it into an intent."""
        # Fix common typos
        user_text = user_text.lower().replace("esay", "essay")

        self.memory.add_message("user", user_text)

        loop = asyncio.get_running_loop()

        def _naive_fallback(text: str) -> Dict[str, Any]:
            text_lower = text.lower().strip()
            if text_lower.startswith("open "):
                return {"intent": "open_app", "target": text_lower[5:].strip(), "confidence": 0.5}
            elif text_lower.startswith("close "):
                return {"intent": "close_app", "target": text_lower[6:].strip(), "confidence": 0.5}
            elif text_lower.startswith("search "):
                return {"intent": "web_search", "target": text_lower[7:].strip(), "confidence": 0.5}
            # Local create_file detection (higher priority than write_text)
            local_cf = _detect_create_file_intent_locally(text)
            if local_cf:
                return local_cf
            # Local write_text detection
            local = _detect_write_intent_locally(text)
            if local:
                return local
            return {"intent": "error", "message": "API Error and could not understand command offline."}

        try:
            logger.info("Using Ollama")
            ollama_raw = await loop.run_in_executor(None, call_ollama, user_text)

            if ollama_raw:
                self.memory.add_message("assistant", ollama_raw)
                parsed = CommandParser.parse(ollama_raw)

                if parsed.get("intent") in ("open_app", "write_text") and _FILE_VERBS.search(user_text):
                    logger.warning(
                        "Ollama returned wrong intent for a file-creation command — retrying."
                    )
                    nudge = (
                        f"The user wants to CREATE a new file and write code into it. "
                        f"Return create_file JSON with target=filename, editor=app, content=full code.\n"
                        f"User command: {user_text}"
                    )
                    retry_raw = await loop.run_in_executor(None, call_ollama, nudge)
                    if retry_raw:
                        retry_parsed = CommandParser.parse(retry_raw)
                        if retry_parsed.get("intent") == "create_file" and retry_parsed.get("content"):
                            logger.info("Retry succeeded — using create_file intent.")
                            return retry_parsed
                    # If retry also failed, fall through to local heuristic
                    local_cf = _detect_create_file_intent_locally(user_text)
                    if local_cf:
                        logger.info("Using local create_file heuristic as last resort.")
                        return local_cf

                # ── Sanity-check: Ollama returned open_app but the user said "write" ──
                # Re-invoke with an explicit nudge so content is actually generated.
                elif parsed.get("intent") == "open_app" and _WRITE_VERBS.search(user_text):
                    logger.warning(
                        "Ollama returned open_app for a write command — retrying with explicit prompt."
                    )
                    nudge = (
                        f"The user wants to write text inside an application. "
                        f"Generate the full text and return write_text JSON.\n"
                        f"User command: {user_text}"
                    )
                    retry_raw = await loop.run_in_executor(None, call_ollama, nudge)
                    if retry_raw:
                        retry_parsed = CommandParser.parse(retry_raw)
                        if retry_parsed.get("intent") == "write_text" and retry_parsed.get("content"):
                            logger.info("Retry succeeded — using write_text intent.")
                            return retry_parsed
                    # If retry also failed, fall through to local heuristic
                    local = _detect_write_intent_locally(user_text)
                    if local:
                        logger.info("Using local write_text heuristic as last resort.")
                        return local

                return parsed

            logger.error("Ollama failed to return response. Falling back to offline parser.")
            return _naive_fallback(user_text)

        except Exception as e:
            logger.error(f"Ollama failed with error: {e}")
            logger.error("Falling back to offline parser.")
            fallback = _naive_fallback(user_text)
            if fallback["intent"] == "error":
                fallback["message"] = f"API Error: {str(e)}"
            return fallback
