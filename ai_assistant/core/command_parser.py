import json
import json_repair
from utils.helpers import setup_logger, json_log
from core.security import validate_command_safety

logger = setup_logger(__name__)


def _fix_json_control_chars(s: str) -> str:
    """
    Escape literal control characters (newlines, carriage-returns, tabs)
    that appear *inside* JSON string values.  phi3 (and other small LLMs)
    often emit raw newlines in multi-line content fields, which makes the
    string invalid JSON even though the overall structure is correct.
    """
    result = []
    in_string = False
    escape_next = False

    for ch in s:
        if escape_next:
            result.append(ch)
            escape_next = False
            continue

        if ch == "\\" and in_string:
            result.append(ch)
            escape_next = True
            continue

        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue

        if in_string:
            if ch == "\n":
                result.append("\\n")
            elif ch == "\r":
                result.append("\\r")
            elif ch == "\t":
                result.append("\\t")
            else:
                result.append(ch)
        else:
            result.append(ch)

    return "".join(result)


def _extract_first_json_payload(s: str) -> str:
    """
    Extract the first balanced JSON object or array from a noisy LLM response.
    This avoids greedy brace matching when the model emits multiple JSON blobs.
    """
    starts = [(s.find("{"), "{", "}"), (s.find("["), "[", "]")]
    starts = [item for item in starts if item[0] != -1]
    if not starts:
        return s

    start_index, opener, closer = min(starts, key=lambda item: item[0])
    depth = 0
    in_string = False
    escape_next = False

    for index in range(start_index, len(s)):
        ch = s[index]

        if escape_next:
            escape_next = False
            continue

        if ch == "\\" and in_string:
            escape_next = True
            continue

        if ch == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return s[start_index:index + 1]

    return s[start_index:]

class CommandParser:
    @staticmethod
    def parse(llm_response: str) -> dict:
        """
        Parse the LLM string response into a JSON dictionary following the new schema:
        { "intent": "open_app", "target": "chrome", "confidence": 0.9, "task": null }
        """
        if not llm_response or not isinstance(llm_response, str):
            logger.error("Invalid AI response received")
            return {
                "intent": "fallback",
                "target": None
            }
        try:
            clean_str = llm_response.strip()
            if clean_str.startswith("```json"):
                clean_str = clean_str[7:]
            elif clean_str.startswith("```"):
                clean_str = clean_str[3:]
                
            if clean_str.endswith("```"):
                clean_str = clean_str[:-3]
                
            clean_str = clean_str.strip()
            # Remove literal line continuations (backslash followed by newline)
            import re
            clean_str = re.sub(r'\\\r?\n', '\n', clean_str)
            
            # Fix literal control characters inside JSON string values
            # (phi3 / small LLMs emit raw newlines in multi-line content)
            clean_str = _fix_json_control_chars(clean_str)

            clean_str = _extract_first_json_payload(clean_str)
                
            command_data = json_repair.loads(clean_str)
            
            if isinstance(command_data, list):
                command_data = next(
                    (item for item in command_data if isinstance(item, dict)),
                    command_data[0] if command_data else {}
                )
                
            if not isinstance(command_data, dict):
                command_data = {}
            
            # Normalization to new intent schema
            # If the old format 'action' is present, convert it to 'intent'
            if "action" in command_data and "intent" not in command_data:
                command_data["intent"] = command_data.pop("action")
            
            if "intent" not in command_data:
                command_data["intent"] = "none"
            
            # Extract target from old fields if present
            if "target" not in command_data:
                if "app" in command_data:
                    command_data["target"] = command_data.pop("app")
                elif "query" in command_data:
                    command_data["target"] = command_data.pop("query")
                elif "url" in command_data:
                    command_data["target"] = command_data.pop("url")
                elif "message" in command_data:
                    command_data["target"] = command_data.pop("message")
                elif "path" in command_data:
                    command_data["target"] = command_data.pop("path")
                else:
                    command_data["target"] = None
                    
            if "confidence" not in command_data:
                command_data["confidence"] = 1.0

            # Security validation (pass action as intent)
            command_data["action"] = command_data["intent"]  # Compatibility for validate_command_safety
            is_safe, reason = validate_command_safety(command_data)
            if not is_safe:
                logger.error(f"Command failed safety check: {reason}")
                return {"intent": "error", "target": None, "message": f"Security block: {reason}"}
            
            # Clean up the compatibility key if we don't need it
            del command_data["action"]

            json_log(logger, "parse_intent", intent=command_data["intent"], target=command_data["target"])
            return command_data
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}\nResponse: {llm_response}")
            return {"intent": "fallback", "target": None, "message": "Failed to understand the command format."}
        except Exception as e:
            logger.error(f"Error parsing command: {e}")
            return {"intent": "fallback", "target": None, "message": str(e)}
