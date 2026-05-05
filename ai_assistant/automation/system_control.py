import os
import platform
from utils.helpers import setup_logger

logger = setup_logger(__name__)

class SystemController:
    @staticmethod
    def execute(operation: str) -> str:
        """Execute a system operation (shutdown, restart, etc)."""
        logger.info(f"Executing system operation: {operation}")
        
        current_os = platform.system().lower()
        
        try:
            if current_os == "windows":
                return SystemController._execute_windows(operation)
            elif current_os == "darwin": # macOS
                return SystemController._execute_macos(operation)
            elif current_os == "linux":
                return SystemController._execute_linux(operation)
            else:
                return f"Unsupported operating system: {current_os}"
        except Exception as e:
            logger.error(f"System control failed: {e}")
            return f"Failed to execute {operation}: {str(e)}"

    @staticmethod
    def _execute_windows(operation: str) -> str:
        if operation == "shutdown":
            os.system("shutdown /s /t 1")
            return "Shutting down the system."
        elif operation == "restart":
            os.system("shutdown /r /t 1")
            return "Restarting the system."
        elif operation == "sleep":
            os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
            return "Putting the system to sleep."
        elif operation == "lock":
            os.system("rundll32.exe user32.dll,LockWorkStation")
            return "Locking the workstation."
        return f"Unknown system operation: {operation}"

    @staticmethod
    def _execute_macos(operation: str) -> str:
        if operation == "shutdown":
            os.system("sudo shutdown -h now")
            return "Shutting down the system."
        elif operation == "restart":
            os.system("sudo shutdown -r now")
            return "Restarting the system."
        elif operation == "sleep":
            os.system("pmset sleepnow")
            return "Putting the system to sleep."
        return f"Unknown system operation: {operation} on macOS"

    @staticmethod
    def _execute_linux(operation: str) -> str:
        if operation == "shutdown":
            os.system("sudo shutdown -h now")
            return "Shutting down the system."
        elif operation == "restart":
            os.system("sudo reboot")
            return "Restarting the system."
        return f"Unknown system operation: {operation} on Linux"
