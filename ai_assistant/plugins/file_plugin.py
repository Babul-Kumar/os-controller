import re
import os
import subprocess
from typing import Optional, Dict, Any
from plugins.base_plugin import Plugin

class FileOpenPlugin(Plugin):
    """Enables “open file <path>” commands."""
    PAT = re.compile(r'open\s+file\s+("?)(.+?)\1$', re.I)

    async def execute(self, command: str) -> Optional[Dict[str, Any]]:
        m = self.PAT.search(command)
        if not m:
            return None
        path = m.group(2).strip()
        if not os.path.exists(path):
            return {
                "status": "not_found",
                "message": f"❌ File not found: {path}",
            }
        try:
            subprocess.Popen(["explorer", path])
            return {
                "status": "success",
                "message": f"✅ Opened file: {path}",
            }
        except Exception as exc:
            return {
                "status": "error",
                "message": f"❌ Could not open file: {exc}",
            }
