import ollama
import json
import re
from utils.helpers import setup_logger

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

def call_ollama(prompt):
    try:
        response = ollama.chat(
            model="llama3",
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        text = response["message"]["content"]
        return text

    except Exception as e:
        logger.error(f"Ollama error: {e}")
        return None
