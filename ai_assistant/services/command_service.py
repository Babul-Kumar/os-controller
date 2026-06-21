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
        import os
        from core.code_intelligence.cache_manager import CacheManager
        workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.cache_manager = CacheManager(workspace_dir)
        self.cache_manager.load_or_rebuild_index()

        self.plugin_manager = PluginManager()
        self.ai_service = AIService(self.cache_manager)
        self.executor = CommandExecutor(self.cache_manager)
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
        
        import time
        from core.metrics_store import get_store
        start_time = time.perf_counter()
        
        action = "none"
        success = True
        error_msg = ""
        response_msg = ""
        
        try:
            # 1. Plugin Pass
            plugin_res = await self.plugin_manager.execute_all(command)
            if plugin_res:
                self._log_history("plugin", command, plugin_res)
                action = "plugin"
                response_msg = plugin_res.get("message", "Plugin executed successfully.")
                success = not (response_msg.startswith("❌") or response_msg.startswith("⚠️") or response_msg.lower().startswith("error"))
                error_msg = "" if success else response_msg
                return response_msg

            # 2. AI Parsing (Intent extraction)
            intent_data = await self.ai_service.process_intent(command)
            action = intent_data.get("intent", "none")
            
            # 3. Task Route
            if intent_data.get("intent") == "task" and intent_data.get("task"):
                task_name = intent_data["task"].lower()
                action = f"task:{task_name}"
                if task_name in self.TASKS:
                    responses = []
                    for sub_cmd in self.TASKS[task_name]:
                        responses.append(await self.process_command(sub_cmd))
                    self._log_history("task", task_name, {"status": "success"})
                    response_msg = f"Executed task '{task_name}': " + " | ".join(responses)
                    success = True
                    return response_msg
                else:
                    response_msg = f"Unknown task: {task_name}"
                    success = False
                    error_msg = response_msg
                    return response_msg

            # 4. Execute via Brain Router
            response_msg = await self.executor.execute_intent(intent_data)
            
            # 5. Log & Return
            self._log_history(action, command, {"status": "executed", "response": response_msg})
            await EventBus.emit("command_completed", {"command": command, "response": response_msg, "intent": intent_data})
            
            success = not (response_msg.startswith("❌") or response_msg.startswith("⚠️") or response_msg.lower().startswith("error") or response_msg.startswith("Unsupported intent") or response_msg.startswith("Execution error"))
            error_msg = "" if success else response_msg
            return response_msg
            
        except Exception as exc:
            success = False
            error_msg = str(exc)
            response_msg = f"❌ System Error: {exc}"
            raise
        finally:
            latency_ms = (time.perf_counter() - start_time) * 1000.0

            # Log to .botbro/usage_metrics.json if it is a code intelligence intent
            if action in ("find_symbol", "find_references", "trace_execution", "list_symbols"):
                try:
                    import os
                    import json
                    metrics_path = os.path.join(self.cache_manager.cache_dir, "usage_metrics.json")
                    metrics_data = []
                    if os.path.exists(metrics_path):
                        with open(metrics_path, "r", encoding="utf-8") as mf:
                            metrics_data = json.load(mf)

                    is_success = not (response_msg.startswith("❌") or response_msg.startswith("⚠️") or "error" in response_msg.lower())

                    metrics_data.append({
                        "query": command,
                        "intent": action,
                        "response_time_ms": latency_ms,
                        "success": is_success
                    })

                    self.cache_manager.save_json_file(metrics_path, metrics_data)
                except Exception as e:
                    logger.error(f"Failed to log usage metrics to json: {e}")

            try:
                get_store().log_command(
                    raw_input=command,
                    action=action,
                    success=success,
                    latency_ms=latency_ms,
                    error_msg=error_msg,
                )
            except Exception as store_exc:
                logger.error(f"Failed to log command metrics: {store_exc}")

    def _log_history(self, action: str, target: str, result: dict):
        entry = {
            "action": action,
            "target": target,
            "timestamp": datetime.datetime.now().isoformat(),
            "result": result
        }
        self.memory.log_command(target, {"action": action, "target": target}, result.get("response", "done"))
