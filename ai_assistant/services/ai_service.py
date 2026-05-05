import asyncio
from typing import Dict, Any, Optional
from config.settings import GEMINI_API_KEY
from utils.helpers import setup_logger, json_log
from core.command_parser import CommandParser
from core.memory import MemoryManager

logger = setup_logger(__name__)

SYSTEM_PROMPT = """You are Botbro, an advanced AI desktop assistant.
Convert the command into STRICT JSON.

Actions/Intents:
- open_app
- close_app
- write_text
- web_search
- open_website
- system_control
- chat_response

Format:
{
  "intent": "...",
  "target": "...",
  "content": "...",
  "confidence": 0.95
}

Examples:
Input: open notepad
Output: {"intent": "open_app", "target": "notepad"}

Input: write an essay on friendship in notepad
Output: {"intent": "write_text", "target": "notepad", "content": "<fully generated essay text goes here>"}

Rules:
- Only JSON
- No explanation
"""

class AIService:
    def __init__(self):
        self.memory = MemoryManager()
        self.client = None
        if GEMINI_API_KEY:
            try:
                from google import genai
                from google.genai import types
                self.client = genai.Client(api_key=GEMINI_API_KEY)
                json_log(logger, "ai_service", status="configured")
            except Exception as e:
                logger.error(f"Failed to initialize AIService: {e}")
    
    async def process_intent(self, user_text: str) -> Dict[str, Any]:
        """Send input to Gemini, get JSON string, parse it into an intent."""
        # Fix common typos
        user_text = user_text.lower().replace("esay", "essay")
        
        if not self.client:
            # Fallback naive parsing if no API key
            return {"intent": "open_app", "target": user_text, "confidence": 0.1}

        self.memory.add_message("user", user_text)
        
        loop = asyncio.get_running_loop()
        
        def _call_llm() -> str:
            from google.genai import types
            import time
            
            max_retries = 3
            base_delay = 1
            
            for attempt in range(max_retries):
                try:
                    response = self.client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=user_text,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT,
                        )
                    )
                    return response.text
                except Exception as e:
                    # Check for 503 Unavailable or 429 Too Many Requests
                    if ("503" in str(e) or "429" in str(e)) and attempt < max_retries - 1:
                        logger.warning(f"Gemini API rate limit/unavailable. Retrying in {base_delay}s...")
                        time.sleep(base_delay)
                        base_delay *= 2
                    else:
                        raise e
            raise Exception("Gemini API exhausted retries")

        def _naive_fallback(text: str) -> Dict[str, Any]:
            text_lower = text.lower().strip()
            if text_lower.startswith("open "):
                return {"intent": "open_app", "target": text_lower[5:].strip(), "confidence": 0.5}
            elif text_lower.startswith("close "):
                return {"intent": "close_app", "target": text_lower[6:].strip(), "confidence": 0.5}
            elif text_lower.startswith("search "):
                return {"intent": "web_search", "target": text_lower[7:].strip(), "confidence": 0.5}
            return {"intent": "error", "message": "API Error and could not understand command offline."}

        try:
            logger.info("Using Gemini")
            raw = await loop.run_in_executor(None, _call_llm)
            self.memory.add_message("assistant", raw)
            intent_data = CommandParser.parse(raw)
            return intent_data
        except Exception as e:
            logger.error(f"Gemini failed: {e}")
            logger.warning("Switching to Ollama fallback...")
            
            # Try Ollama Fallback
            from services.ollama_service import call_ollama
            ollama_raw = await loop.run_in_executor(None, call_ollama, user_text)
            
            if ollama_raw:
                self.memory.add_message("assistant", ollama_raw)
                return CommandParser.parse(ollama_raw)
                
            logger.error("Ollama fallback failed. Falling back to offline parser.")
            fallback = _naive_fallback(user_text)
            if fallback["intent"] == "error":
                fallback["message"] = f"API Error: {str(e)}"
            return fallback
