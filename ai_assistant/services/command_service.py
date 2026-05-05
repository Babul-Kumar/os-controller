import asyncio
import datetime
from typing import Dict, Any
from utils.helpers import setup_logger, json_log
from core.plugin_manager import PluginManager
from services.ai_service import AIService
from core.executor import CommandExecutor
from core.memory import MemoryManager
from core.event_bus import EventBus

logger = setup_logger(__name__)

class CommandService:
    """Middle layer: routes GUI inputs through plugins -> AI -> Executor -> Voice/GUI."""
    def __init__(self):
        self.plugin_manager = PluginManager()
        self.ai_service = AIService()
        self.executor = CommandExecutor()
        self.memory = MemoryManager()
        
        # Hardcoded tasks for TaskEngine replacement
        self.TASKS = {
            "work mode": ["open chrome", "open vscode", "open slack"],
            "music mode": ["open spotify", "play music"]
        }

    async def process_command(self, raw_command: str) -> str:
        command = raw_command.strip()
        logger.info(f"CommandService processing: {command}")
        
        await EventBus.emit("command_received", {"command": command})

        # 1. Plugin Pass
        plugin_res = await self.plugin_manager.execute_all(command)
        if plugin_res:
            self._log_history("plugin", command, plugin_res)
            return plugin_res.get("message", "Plugin executed successfully.")

        # 2. AI Parsing (Intent extraction)
        intent_data = await self.ai_service.process_intent(command)
        
        # 3. Task Route
        if intent_data.get("intent") == "task" and intent_data.get("task"):
            task_name = intent_data["task"].lower()
            if task_name in self.TASKS:
                responses = []
                for sub_cmd in self.TASKS[task_name]:
                    responses.append(await self.process_command(sub_cmd))
                self._log_history("task", task_name, {"status": "success"})
                return f"Executed task '{task_name}': " + " | ".join(responses)
            else:
                return f"Unknown task: {task_name}"

        # 4. Execute via Brain Router
        response_msg = await self.executor.execute_intent(intent_data)
        
        # 5. Log & Return
        self._log_history(intent_data.get("intent", "none"), command, {"status": "executed", "response": response_msg})
        await EventBus.emit("command_completed", {"command": command, "response": response_msg, "intent": intent_data})
        
        return response_msg

    def _log_history(self, action: str, target: str, result: dict):
        entry = {
            "action": action,
            "target": target,
            "timestamp": datetime.datetime.now().isoformat(),
            "result": result
        }
        self.memory.log_command(target, {"action": action, "target": target}, result.get("response", "done"))
