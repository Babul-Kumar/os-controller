"""
vector_memory.py — FAISS-backed semantic memory for Botbro.

Stores and retrieves conversation history, user preferences, and project
context using dense vector embeddings. Falls back to keyword search if
FAISS or sentence-transformers are not installed.

Storage:
  - FAISS index: memory_index.faiss (next to memory.db)
  - Metadata: memory.db 'memory_entries' table (managed by MemoryManager)

Public API:
  - VectorMemory.remember(content, metadata) -> str
  - VectorMemory.recall(query, top_k) -> List[MemoryEntry]
  - VectorMemory.learn_preference(key, value)
  - VectorMemory.get_preferences() -> dict
  - VectorMemory.format_for_prompt(entries) -> str
"""

import os
import json
import sqlite3
import uuid
import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

import numpy as np

from config.settings import DB_PATH
from utils.helpers import setup_logger

logger = setup_logger(__name__)

# ── Optional dependency guards ────────────────────────────────────────────────

try:
    import faiss  # type: ignore
    _FAISS_AVAILABLE = True
except ImportError:
    _FAISS_AVAILABLE = False
    logger.warning("FAISS not installed. Using keyword fallback for memory recall.")

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
    _ST_AVAILABLE = True
except ImportError:
    _ST_AVAILABLE = False
    logger.warning("sentence-transformers not installed. Vector memory disabled.")

# ── Constants ─────────────────────────────────────────────────────────────────

EMBEDDING_DIM = 384          # all-MiniLM-L6-v2 output dimension
_MODEL_NAME   = "all-MiniLM-L6-v2"


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class MemoryEntry:
    """A single semantic memory record returned by recall()."""
    id: str
    content: str
    metadata: Dict[str, Any]
    similarity: float
    timestamp: str


# ── Core class ────────────────────────────────────────────────────────────────

class VectorMemory:
    """
    FAISS-backed semantic memory store.

    When FAISS / sentence-transformers are unavailable the class degrades
    gracefully to plain SQLite keyword search so the rest of Botbro keeps
    working without any changes to calling code.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        index_path: Optional[str] = None,
    ) -> None:
        """
        Initialise the vector memory.

        Args:
            db_path:    Path to the SQLite database (defaults to DB_PATH from
                        settings).
            index_path: Path where the FAISS index is persisted (defaults to
                        <db_dir>/memory_index.faiss).
        """
        self.db_path = db_path or DB_PATH

        # Derive index path from db_path if not supplied
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        self.index_path = index_path or os.path.join(db_dir, "memory_index.faiss")

        # Lazy-loaded sentence-transformer model
        self._embedder: Optional["SentenceTransformer"] = None  # type: ignore[name-defined]

        # FAISS index (None if FAISS unavailable or not yet loaded)
        self._index: Optional[Any] = None

        # Counts total vectors added so we can assign FAISS positions
        self._next_embedding_id: int = 0

        self._init_db()
        self.load_index()

    # ── DB initialisation ─────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Create the memory_entries table if it does not already exist."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS memory_entries (
                        id           TEXT PRIMARY KEY,
                        content      TEXT,
                        metadata     TEXT,
                        embedding_id INTEGER,
                        timestamp    TEXT
                    )
                """)
                conn.commit()
            # Sync next_embedding_id from the current max stored
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT MAX(embedding_id) FROM memory_entries"
                ).fetchone()
                if row and row[0] is not None:
                    self._next_embedding_id = int(row[0]) + 1
            logger.debug("VectorMemory DB initialised at %s", self.db_path)
        except Exception as exc:
            logger.error("VectorMemory._init_db failed: %s", exc)

    # ── Embedding helpers ─────────────────────────────────────────────────────

    def _get_embedder(self) -> Optional["SentenceTransformer"]:  # type: ignore[name-defined]
        """Lazily load the SentenceTransformer model on first use."""
        if not _ST_AVAILABLE:
            return None
        if self._embedder is None:
            try:
                logger.info("Loading SentenceTransformer model '%s' …", _MODEL_NAME)
                self._embedder = SentenceTransformer(_MODEL_NAME)  # type: ignore[name-defined]
                logger.info("SentenceTransformer model loaded.")
            except Exception as exc:
                logger.error("Failed to load SentenceTransformer: %s", exc)
                return None
        return self._embedder

    def embed(self, text: str) -> Optional[np.ndarray]:
        """
        Return a 384-dim float32 unit-norm embedding for *text*.

        Returns None when sentence-transformers is unavailable.
        """
        embedder = self._get_embedder()
        if embedder is None:
            return None
        try:
            vec = embedder.encode([text], convert_to_numpy=True).astype(np.float32)
            # Normalise in-place so inner product == cosine similarity
            faiss.normalize_L2(vec) if _FAISS_AVAILABLE else None  # type: ignore[union-attr]
            return vec  # shape (1, 384)
        except Exception as exc:
            logger.error("embed() failed: %s", exc)
            return None

    # ── FAISS index helpers ───────────────────────────────────────────────────

    def _get_or_create_index(self) -> Optional[Any]:
        """Return the FAISS index, creating it if necessary."""
        if not _FAISS_AVAILABLE:
            return None
        if self._index is None:
            try:
                self._index = faiss.IndexFlatIP(EMBEDDING_DIM)  # inner-product
                logger.debug("Created new FAISS IndexFlatIP(dim=%d)", EMBEDDING_DIM)
            except Exception as exc:
                logger.error("Failed to create FAISS index: %s", exc)
        return self._index

    def save_index(self) -> None:
        """Persist the FAISS index to disk."""
        if not _FAISS_AVAILABLE or self._index is None:
            return
        try:
            faiss.write_index(self._index, self.index_path)
            logger.debug("FAISS index saved to %s", self.index_path)
        except Exception as exc:
            logger.error("save_index() failed: %s", exc)

    def load_index(self) -> None:
        """Load a FAISS index from disk if the file exists."""
        if not _FAISS_AVAILABLE:
            return
        if os.path.exists(self.index_path):
            try:
                self._index = faiss.read_index(self.index_path)
                logger.info(
                    "FAISS index loaded from %s (%d vectors)",
                    self.index_path,
                    self._index.ntotal,
                )
            except Exception as exc:
                logger.error("load_index() failed: %s — starting fresh.", exc)
                self._index = None

    # ── Public memory API ─────────────────────────────────────────────────────

    def remember(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Store *content* in both FAISS and SQLite.

        Args:
            content:  The text to remember.
            metadata: Arbitrary JSON-serialisable dict (e.g. type, intent).

        Returns:
            The generated entry ID (12-char hex string).
        """
        entry_id  = uuid.uuid4().hex[:12]
        timestamp = datetime.datetime.now().isoformat()
        metadata  = metadata or {}

        # Embed and add to FAISS
        embedding_id = -1
        vec = self.embed(content)
        index = self._get_or_create_index()
        if vec is not None and index is not None:
            try:
                index.add(vec)
                embedding_id = self._next_embedding_id
                self._next_embedding_id += 1
                self.save_index()
            except Exception as exc:
                logger.error("FAISS add failed: %s", exc)

        # Persist metadata to SQLite
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO memory_entries (id, content, metadata, embedding_id, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (entry_id, content, json.dumps(metadata), embedding_id, timestamp),
                )
                conn.commit()
        except Exception as exc:
            logger.error("remember() SQLite insert failed: %s", exc)

        logger.debug("Stored memory entry %s", entry_id)
        return entry_id

    def recall(
        self,
        query: str,
        top_k: int = 5,
    ) -> List[MemoryEntry]:
        """
        Retrieve the *top_k* most semantically similar entries for *query*.

        Falls back to case-insensitive keyword search in SQLite when FAISS or
        sentence-transformers are unavailable.

        Args:
            query: The search query.
            top_k: Maximum number of results.

        Returns:
            List of MemoryEntry objects sorted by descending similarity.
        """
        # ── Vector path ───────────────────────────────────────────────────────
        index = self._get_or_create_index()
        vec   = self.embed(query)

        if vec is not None and index is not None and index.ntotal > 0:
            try:
                k = min(top_k, index.ntotal)
                scores, positions = index.search(vec, k)
                # scores / positions are shape (1, k)
                pos_score_pairs = list(zip(positions[0], scores[0]))

                # Fetch all metadata in one query then filter by embedding_id
                with sqlite3.connect(self.db_path) as conn:
                    rows = conn.execute(
                        "SELECT id, content, metadata, embedding_id, timestamp FROM memory_entries"
                    ).fetchall()

                # Build a lookup: embedding_id -> row
                row_by_eid: Dict[int, tuple] = {r[3]: r for r in rows if r[3] >= 0}

                entries: List[MemoryEntry] = []
                for pos, score in pos_score_pairs:
                    if pos < 0:
                        continue
                    row = row_by_eid.get(int(pos))
                    if row is None:
                        continue
                    try:
                        meta = json.loads(row[2]) if row[2] else {}
                    except json.JSONDecodeError:
                        meta = {}
                    entries.append(
                        MemoryEntry(
                            id=row[0],
                            content=row[1],
                            metadata=meta,
                            similarity=float(score),
                            timestamp=row[4],
                        )
                    )
                return entries
            except Exception as exc:
                logger.error("FAISS recall failed, falling back to keyword: %s", exc)

        # ── Keyword fallback ──────────────────────────────────────────────────
        logger.debug("Using keyword fallback for recall('%s')", query)
        return self._keyword_recall(query, top_k)

    def _keyword_recall(self, query: str, top_k: int) -> List[MemoryEntry]:
        """SQLite LIKE-based keyword search used when FAISS is unavailable."""
        try:
            keyword = f"%{query}%"
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT id, content, metadata, embedding_id, timestamp
                    FROM memory_entries
                    WHERE content LIKE ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (keyword, top_k),
                ).fetchall()
            entries: List[MemoryEntry] = []
            for row in rows:
                try:
                    meta = json.loads(row[2]) if row[2] else {}
                except json.JSONDecodeError:
                    meta = {}
                entries.append(
                    MemoryEntry(
                        id=row[0],
                        content=row[1],
                        metadata=meta,
                        similarity=0.0,   # no real score in keyword mode
                        timestamp=row[4],
                    )
                )
            return entries
        except Exception as exc:
            logger.error("_keyword_recall() failed: %s", exc)
            return []

    def learn_preference(self, key: str, value: str) -> str:
        """
        Shorthand to store a user preference as a memory entry.

        Args:
            key:   Preference key (e.g. 'preferred_editor_py').
            value: Preference value (e.g. 'vscode').

        Returns:
            Entry ID of the stored preference.
        """
        return self.remember(
            f"{key}: {value}",
            {"type": "preference", "key": key, "value": value},
        )

    def get_preferences(self) -> Dict[str, str]:
        """
        Return all stored user preferences as a flat {key: value} dict.

        Queries SQLite directly for entries whose metadata contains
        ``"type": "preference"``.
        """
        prefs: Dict[str, str] = {}
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT metadata FROM memory_entries"
                ).fetchall()
            for (meta_str,) in rows:
                try:
                    meta = json.loads(meta_str) if meta_str else {}
                except json.JSONDecodeError:
                    continue
                if meta.get("type") == "preference":
                    k = meta.get("key")
                    v = meta.get("value")
                    if k and v:
                        prefs[k] = v
        except Exception as exc:
            logger.error("get_preferences() failed: %s", exc)
        return prefs

    # ── Prompt formatting ─────────────────────────────────────────────────────

    def format_for_prompt(self, entries: List[MemoryEntry]) -> str:
        """
        Format a list of MemoryEntry objects as a short bulleted string
        suitable for injection into an LLM system prompt.

        Example output::

            Relevant memories:
            - User said: open vscode (similarity: 0.92)
            - preferred_editor_py: vscode (similarity: 0.88)

        Args:
            entries: List of MemoryEntry objects (from recall()).

        Returns:
            Multi-line string, or empty string if entries is empty.
        """
        if not entries:
            return ""
        lines = ["Relevant memories:"]
        for entry in entries:
            sim_str = f" (similarity: {entry.similarity:.2f})" if entry.similarity > 0 else ""
            # Truncate very long entries for brevity
            snippet = entry.content[:120] + "…" if len(entry.content) > 120 else entry.content
            lines.append(f"- {snippet}{sim_str}")
        return "\n".join(lines)
