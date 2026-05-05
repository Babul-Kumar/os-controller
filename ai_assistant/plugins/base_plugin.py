from typing import Optional, Dict, Any

class Plugin:
    """Base class for all dynamically loaded plugins."""
    
    @property
    def name(self) -> str:
        return self.__class__.__name__

    async def execute(self, command: str) -> Optional[Dict[str, Any]]:
        """
        Evaluate the command. If the plugin can handle it, return a dict with status and message.
        If it cannot, return None.
        """
        raise NotImplementedError
