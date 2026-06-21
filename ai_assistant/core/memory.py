import sqlite3
import json
import datetime
from typing import List
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
            
            # Create vector memory entries table (Phase 3 — RAG Memory)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS memory_entries (
                    id           TEXT PRIMARY KEY,
                    content      TEXT,
                    metadata     TEXT,
                    embedding_id INTEGER,
                    timestamp    TEXT
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

    # ── Phase 3: Vector memory CRUD ──────────────────────────────────────────

    def store_memory_entry(
        self,
        id: str,
        content: str,
        metadata: dict,
        embedding_id: int,
    ) -> None:
        """Persist a vector memory entry to the memory_entries table."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            timestamp = datetime.datetime.now().isoformat()
            cursor.execute(
                """
                INSERT OR REPLACE INTO memory_entries
                    (id, content, metadata, embedding_id, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (id, content, json.dumps(metadata), embedding_id, timestamp),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to store memory entry: {e}")

    def get_memory_entries_by_type(self, entry_type: str) -> List[dict]:
        """
        Return all memory entries whose metadata JSON contains
        ``'type': entry_type``.
        """
        results: List[dict] = []
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, content, metadata, embedding_id, timestamp FROM memory_entries"
            )
            rows = cursor.fetchall()
            conn.close()
            for row in rows:
                try:
                    meta = json.loads(row[2]) if row[2] else {}
                except json.JSONDecodeError:
                    meta = {}
                if meta.get("type") == entry_type:
                    results.append({
                        "id":           row[0],
                        "content":      row[1],
                        "metadata":     meta,
                        "embedding_id": row[3],
                        "timestamp":    row[4],
                    })
        except Exception as e:
            logger.error(f"Failed to get memory entries by type: {e}")
        return results

    def get_all_memory_entries(self, limit: int = 200) -> List[dict]:
        """Return up to *limit* memory entries ordered by most recent first."""
        results: List[dict] = []
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, content, metadata, embedding_id, timestamp
                FROM memory_entries
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            conn.close()
            for row in rows:
                try:
                    meta = json.loads(row[2]) if row[2] else {}
                except json.JSONDecodeError:
                    meta = {}
                results.append({
                    "id":           row[0],
                    "content":      row[1],
                    "metadata":     meta,
                    "embedding_id": row[3],
                    "timestamp":    row[4],
                })
        except Exception as e:
            logger.error(f"Failed to get all memory entries: {e}")
        return results

    def delete_memory_entry(self, entry_id: str) -> None:
        """Remove a single memory entry by its ID."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM memory_entries WHERE id = ?", (entry_id,)
            )
            conn.commit()
            conn.close()
            logger.debug(f"Deleted memory entry {entry_id}")
        except Exception as e:
            logger.error(f"Failed to delete memory entry {entry_id}: {e}")
