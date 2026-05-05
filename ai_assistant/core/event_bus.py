from typing import Callable, Dict, List, Any
import asyncio
from utils.helpers import setup_logger, json_log

logger = setup_logger(__name__)

class EventBus:
    """
    Asynchronous Event Bus for decoupled module communication.
    Supports subscribing to events and emitting them.
    """
    _subscribers: Dict[str, List[Callable]] = {}

    @classmethod
    def on(cls, event_name: str, handler: Callable):
        """Register a handler for a specific event."""
        if event_name not in cls._subscribers:
            cls._subscribers[event_name] = []
        if handler not in cls._subscribers[event_name]:
            cls._subscribers[event_name].append(handler)
            logger.debug(f"Subscribed handler {handler.__name__} to event '{event_name}'")

    @classmethod
    def off(cls, event_name: str, handler: Callable):
        """Unregister a handler for a specific event."""
        if event_name in cls._subscribers:
            try:
                cls._subscribers[event_name].remove(handler)
            except ValueError:
                pass

    @classmethod
    async def emit(cls, event_name: str, data: Any = None):
        """Emit an event asynchronously to all registered handlers."""
        if event_name in cls._subscribers:
            handlers = cls._subscribers[event_name]
            # json_log(logger, "event_emit", event=event_name, num_handlers=len(handlers))
            
            tasks = []
            for handler in handlers:
                if asyncio.iscoroutinefunction(handler):
                    tasks.append(asyncio.create_task(handler(data)))
                else:
                    # Run synchronous handlers in executor to not block event loop
                    loop = asyncio.get_running_loop()
                    tasks.append(loop.run_in_executor(None, handler, data))
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
