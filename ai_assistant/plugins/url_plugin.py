import re
import subprocess
from typing import Optional, Dict, Any
from plugins.base_plugin import Plugin

class URLPlugin(Plugin):
    """Open a URL via the default browser."""
    PAT = re.compile(r'open\s+url\s+("?)(https?://.+?)\1$', re.I)

    async def execute(self, command: str) -> Optional[Dict[str, Any]]:
        m = self.PAT.search(command)
        if not m:
            return None
        url = m.group(2).strip()
        try:
            # Use the Windows “start” command which opens the default browser
            subprocess.Popen(f'start "" "{url}"', shell=True)
            return {
                "status": "success",
                "message": f"✅ Opened URL: {url}",
            }
        except Exception as exc:
            return {
                "status": "error",
                "message": f"❌ Could not open URL: {exc}",
            }
