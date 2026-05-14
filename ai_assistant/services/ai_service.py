import re
import asyncio
from typing import Dict, Any, Optional
from utils.helpers import setup_logger, json_log
from core.command_parser import CommandParser
from core.memory import MemoryManager
from core.pii_engine import PIIEngine
from services.ollama_service import call_ollama

logger = setup_logger(__name__)

# Draw verbs to detect draw intent locally
_DRAW_VERBS = re.compile(
    r"\b(draw|sketch|paint|illustrate|doodle)\b", re.IGNORECASE
)

# Stop words to exclude when extracting draw subjects
_DRAW_STOP_WORDS = {
    "a", "an", "the", "in", "it", "on", "and", "or", "with",
    "open", "paint", "draw", "sketch", "me", "please", "now",
    "make", "create", "show",
}

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
    app name, return a write_text intent with a fallback content.
    """
    tl = text.lower()
    if not _WRITE_VERBS.search(tl):
        return None
    for app in _WRITABLE_APPS:
        if app in tl:
            return {"intent": "write_text", "target": app, "content": "[Botbro Offline/Fallback] I am unable to generate the requested content.", "confidence": 0.6}
    return None
def _detect_draw_intent_locally(text: str):
    """
    Local heuristic: if the user's text contains a draw verb, extract
    the subject that follows it and return a draw_shape intent dict.
    Returns None if no draw verb is found.
    """
    tl = text.lower()
    if not _DRAW_VERBS.search(tl):
        return None

    # Try to extract the noun phrase after the draw verb
    # Pattern: (draw/sketch/paint) [a/an/the] <subject words>
    m = re.search(
        r"\b(?:draw|sketch|paint|illustrate|doodle)\s+(?:a\s+|an\s+|the\s+)?(.+)",
        tl, re.IGNORECASE
    )
    if m:
        raw = m.group(1).strip()
        # Remove trailing noise words like "in it", "in paint", etc.
        raw = re.sub(r"\s+(in\s+\w+|for\s+\w+|on\s+\w+)$", "", raw).strip()
        # Filter stop words from multi-word subjects
        tokens = [w for w in raw.split() if w not in _DRAW_STOP_WORDS]
        subject = " ".join(tokens).strip()
        if subject:
            return {"intent": "draw_shape", "target": subject, "confidence": 0.85}

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
            elif text_lower.startswith("read file "):
                return {"intent": "read_file", "target": text_lower[10:].strip(), "confidence": 0.5}
            elif text_lower.startswith("delete file "):
                return {"intent": "delete_file", "target": text_lower[12:].strip(), "confidence": 0.5}
            elif text_lower.startswith("list directory ") or text_lower.startswith("list dir "):
                target = text_lower.replace("list directory", "").replace("list dir", "").strip()
                return {"intent": "list_directory", "target": target, "confidence": 0.5}
            elif text_lower.startswith("modify file "):
                return {"intent": "modify_file", "target": text_lower[12:].strip(), "content": "Updated content.", "confidence": 0.5}
            elif text_lower.startswith("run command ") or text_lower.startswith("execute command "):
                cmd = text_lower[12:].strip() if text_lower.startswith("run command ") else text_lower[16:].strip()
                return {"intent": "execute_command", "target": cmd, "confidence": 0.5}
            
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
            
            # PII Tokenization Phase
            engine = PIIEngine()
            safe_text, pii_context = engine.tokenize(user_text)

            ollama_raw = await loop.run_in_executor(None, call_ollama, safe_text)

            if ollama_raw:
                # PII Restoration Phase
                if pii_context.has_pii():
                    ollama_raw = engine.restore(ollama_raw, pii_context)

                self.memory.add_message("assistant", ollama_raw)
                parsed = CommandParser.parse(ollama_raw)

                if parsed.get("intent") in ("open_app", "write_text") and _FILE_VERBS.search(user_text):
                    logger.warning(
                        "Ollama returned wrong intent for a file-creation command — retrying."
                    )
                    nudge = (
                        f"The user wants to CREATE a new file and write code into it. "
                        f"Return create_file JSON with target=filename, editor=app, content=full code.\n"
                        f"User command: {safe_text}"
                    )
                    retry_raw = await loop.run_in_executor(None, call_ollama, nudge)
                    if retry_raw:
                        if pii_context.has_pii():
                            retry_raw = engine.restore(retry_raw, pii_context)
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
                        f"User command: {safe_text}"
                    )
                    retry_raw = await loop.run_in_executor(None, call_ollama, nudge)
                    if retry_raw:
                        if pii_context.has_pii():
                            retry_raw = engine.restore(retry_raw, pii_context)
                        retry_parsed = CommandParser.parse(retry_raw)
                        if retry_parsed.get("intent") == "write_text" and retry_parsed.get("content"):
                            logger.info("Retry succeeded — using write_text intent.")
                            return retry_parsed
                    # If retry also failed, fall through to local heuristic
                    local = _detect_write_intent_locally(user_text)
                    if local:
                        logger.info("Using local write_text heuristic as last resort.")
                        return local

                # ── draw_shape sanity check ─────────────────────────────────
                # phi3 sometimes hallucinates the draw target (e.g. returns
                # "anime girl" when user said "cat").  Verify the parsed target
                # actually appears in the user's text; if not, fall back to
                # the locally extracted subject.
                if parsed.get("intent") == "draw_shape":
                    llm_target  = (parsed.get("target") or "").lower().strip()
                    user_lower  = user_text.lower()
                    target_words = llm_target.split()
                    target_in_text = any(
                        w in user_lower for w in target_words if len(w) > 2
                    )
                    if not target_in_text:
                        logger.warning(
                            f"draw_shape hallucination detected: LLM said '{llm_target}' "
                            f"but user said '{user_text}'. Extracting target locally."
                        )
                        local_draw = _detect_draw_intent_locally(user_text)
                        if local_draw:
                            logger.info(f"Corrected draw target to: '{local_draw['target']}'")
                            return local_draw

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
