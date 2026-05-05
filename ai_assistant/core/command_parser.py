import json
from utils.helpers import setup_logger, json_log
from core.security import validate_command_safety

logger = setup_logger(__name__)

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
            
            # Find the first '{' and the last '}' just in case
            # Try to extract JSON using regex
            import re
            match = re.search(r"\{.*\}", clean_str, re.DOTALL)
            if match:
                clean_str = match.group(0)
            else:
                # If no braces found, maybe it's completely malformed
                pass
                
            command_data = json.loads(clean_str)
            
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
