import pyautogui
import time
from automation.system_control import SystemController
from automation.app_controller import AppController
from automation.file_manager import FileManager
from automation.web_automation import WebAutomator
from utils.helpers import setup_logger, json_log

logger = setup_logger(__name__)

class CommandExecutor:
    """The central Brain Router that acts on Intents."""
    def __init__(self):
        self.web_automator = WebAutomator()

    async def execute_intent(self, intent_data: dict) -> str:
        intent = intent_data.get("intent", "none")
        target = intent_data.get("target", "")
        
        if intent in ("none", "error", "fallback"):
            return intent_data.get("message", "⚠️ I couldn't understand that. Please try again.")

        logger.info(f"Executing intent: {intent} on target: {target}")

        try:
            if intent == "open_app":
                res = await AppController.open_app(target)
                return res.get("message", "Executed open_app")
                
            elif intent == "close_app":
                res = await AppController.close_app(target)
                return res.get("message", "Executed close_app")
                
            elif intent == "write_text":
                content = intent_data.get("content", target)
                app_target = intent_data.get("target")
                
                if app_target and app_target != content and app_target != "none":
                    await AppController.open_app(app_target)
                    time.sleep(2)  # Wait for app to open
                    
                if content:
                    time.sleep(1)
                    pyautogui.write(content, interval=0.01)
                    return f"✅ Text written successfully"
                return "Error: No text provided to type."
                
            elif intent == "web_search":
                return self.web_automator.search_google(target)
                
            elif intent == "open_website":
                return self.web_automator.open_website(target)
                
            elif intent == "system_control":
                # Assuming target holds the operation like "shutdown", "sleep"
                operation = intent_data.get("operation") or target
                return SystemController.execute(operation)
                
            elif intent == "chat_response":
                return target
                
            else:
                return f"Unsupported intent: {intent}"
                
        except Exception as e:
            logger.error(f"Execution failed for intent {intent}: {e}")
            return f"Execution error: {str(e)}"
