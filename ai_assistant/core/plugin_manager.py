import os
import importlib
import inspect
from typing import List, Optional, Dict, Any
from plugins.base_plugin import Plugin
from utils.helpers import setup_logger, json_log

logger = setup_logger(__name__)

class PluginManager:
    """Dynamically loads and manages plugins from the plugins directory."""
    
    def __init__(self):
        self.plugins: List[Plugin] = []
        self._load_plugins()

    def _load_plugins(self):
        plugins_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins")
        if not os.path.exists(plugins_dir):
            return

        for filename in os.listdir(plugins_dir):
            if filename.endswith(".py") and not filename.startswith("__") and filename != "base_plugin.py":
                module_name = f"plugins.{filename[:-3]}"
                try:
                    module = importlib.import_module(module_name)
                    for name, obj in inspect.getmembers(module):
                        if inspect.isclass(obj) and issubclass(obj, Plugin) and obj is not Plugin:
                            plugin_instance = obj()
                            self.plugins.append(plugin_instance)
                            json_log(logger, "plugin_loaded", name=plugin_instance.name)
                except Exception as e:
                    logger.error(f"Failed to load plugin {module_name}: {e}")

    async def execute_all(self, command: str) -> Optional[Dict[str, Any]]:
        """Pass the command to all plugins. Return the first successful result."""
        for plugin in self.plugins:
            try:
                result = await plugin.execute(command)
                if result is not None:
                    json_log(logger, "plugin_executed", plugin=plugin.name, command=command, status=result.get("status"))
                    return result
            except Exception as e:
                logger.error(f"Plugin {plugin.name} failed during execution: {e}")
        return None
