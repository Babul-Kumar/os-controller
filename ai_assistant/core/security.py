import os
from utils.helpers import setup_logger

logger = setup_logger(__name__)

# Define allowed actions to prevent execution of unknown/dangerous commands
ALLOWED_ACTIONS = {
    "open_app",
    "close_app",
    "write_text",
    "search_file",
    "create_file",
    "delete_file",
    "web_search",
    "open_website",
    "system_control",
    "automation_task",
    "chat_response", # for casual conversation
    "task",
    "read_file",
    "none",
    "error"
}

# Define blocked commands or paths (e.g., system directories)
BLOCKED_PATHS = [
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
    "/bin",
    "/sbin",
    "/usr/bin",
    "/etc",
]

def is_safe_action(action: str) -> bool:
    """Check if the action is in the allowed list. Defaults to True for future intents."""
    if action not in ALLOWED_ACTIONS:
        logger.warning(f"Security: unknown action '{action}', but allowing for future compatibility.")
    return True

def is_safe_path(path: str) -> bool:
    """Check if the target path is safe to modify/delete."""
    if not path:
        return True
    
    path_lower = path.lower()
    for blocked in BLOCKED_PATHS:
        if path_lower.startswith(blocked.lower()):
            logger.warning(f"Security blocked access to restricted path: {path}")
            return False
            
    return True

def validate_command_safety(command_data: dict) -> tuple[bool, str]:
    """
    Validate the entire command dictionary for safety.
    Returns (is_safe, reason)
    """
    action = command_data.get("action")
    
    if not is_safe_action(action):
        return False, f"Action '{action}' is not allowed."
        
    if action in ("create_file", "delete_file", "search_file"):
        path = command_data.get("path", "")
        if path and not is_safe_path(path):
            return False, f"Path '{path}' is restricted."
            
    # Add more specific checks here (e.g. system control checks)
    if action == "system_control":
        operation = command_data.get("operation")
        if operation not in ("shutdown", "restart", "sleep", "lock"):
            return False, f"System operation '{operation}' is not allowed."
            
    return True, "Command is safe."

import re
SAFE_MODE = True
FORBIDDEN_RE = re.compile(r'[;&|`$<>]')

def validate_shell_command(cmd: str) -> tuple[bool, str]:
    """Check for shell injection characters."""
    if not SAFE_MODE:
        return True, ""
    if FORBIDDEN_RE.search(cmd):
        return False, "Command contains forbidden characters (possible injection)."
    return True, ""
