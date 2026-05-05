import sqlite3
import json
import datetime
from config.settings import DB_PATH
from utils.helpers import setup_logger

logger = setup_logger(__name__)

class MemoryManager:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()
        
    def _init_db(self):
        """Initialize the SQLite database with the required tables."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create conversation history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    role TEXT,
                    content TEXT
                )
            ''')
            
            # Create command history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS command_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    raw_input TEXT,
                    parsed_json TEXT,
                    execution_status TEXT
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info(f"Database initialized at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")

    def add_message(self, role: str, content: str):
        """Add a message to the conversation history."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            timestamp = datetime.datetime.now().isoformat()
            cursor.execute(
                "INSERT INTO conversation_history (timestamp, role, content) VALUES (?, ?, ?)",
                (timestamp, role, content)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to add message to memory: {e}")

    def log_command(self, raw_input: str, parsed_json: dict, execution_status: str):
        """Log an executed command."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            timestamp = datetime.datetime.now().isoformat()
            cursor.execute(
                "INSERT INTO command_history (timestamp, raw_input, parsed_json, execution_status) VALUES (?, ?, ?, ?)",
                (timestamp, raw_input, json.dumps(parsed_json), execution_status)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to log command: {e}")

    def get_recent_context(self, limit=5):
        """Retrieve recent conversation context to feed to the LLM."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT role, content FROM conversation_history ORDER BY id DESC LIMIT ?", 
                (limit,)
            )
            rows = cursor.fetchall()
            conn.close()
            
            # Return in chronological order
            return [{"role": role, "parts": [content]} for role, content in reversed(rows)]
        except Exception as e:
            logger.error(f"Failed to get context: {e}")
            return []

    def get_favorite_apps(self, limit=5):
        """Analyze command history to find most frequently opened apps."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT parsed_json FROM command_history ORDER BY id DESC LIMIT 100")
            rows = cursor.fetchall()
            conn.close()
            
            app_counts = {}
            for row in rows:
                try:
                    data = json.loads(row[0])
                    # Handle both old format ("action": "open_app", "app": "name") and new ("action": "open", "target": "name")
                    if data.get("action") in ("open_app", "open"):
                        target = data.get("app") or data.get("target")
                        if target:
                            app_counts[target] = app_counts.get(target, 0) + 1
                except Exception:
                    pass
            
            sorted_apps = sorted(app_counts.items(), key=lambda item: item[1], reverse=True)
            return [app for app, count in sorted_apps[:limit]]
        except Exception as e:
            logger.error(f"Failed to get favorite apps: {e}")
            return []

    def suggest_next_app(self):
        """Provide a contextual suggestion based on recent history."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT parsed_json FROM command_history ORDER BY id DESC LIMIT 5")
            rows = cursor.fetchall()
            conn.close()
            
            recent_opens = []
            for row in rows:
                try:
                    data = json.loads(row[0])
                    if data.get("action") in ("open_app", "open"):
                        target = data.get("app") or data.get("target")
                        if target:
                            recent_opens.append(target.lower())
                except Exception:
                    pass
            
            # --- coding -> terminal ---
            if any(kw in t for t in recent_opens for kw in ("vscode", "code", "pycharm")):
                return "terminal"

            # --- browsing -> mail ---
            if any("chrome" in t or "browser" in t for t in recent_opens):
                return "mail"
                
            return None
        except Exception as e:
            logger.error(f"Failed to suggest next app: {e}")
            return None
