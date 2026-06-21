"""
metrics_store.py
─────────────────
Central SQLite metrics layer for the Performance Dashboard.

Tables managed here
────────────────────
  stt_metrics      — already seeded by WhisperSTT / stt_benchmark.py
  command_metrics  — every command sent through CommandService
  agent_metrics    — every agent pipeline run (Planner/Coder/Executor/Verifier)
  ocr_metrics      — every Tesseract / screen-capture call
  workflow_metrics — every Teach-Botbro macro replay

All write methods are fire-and-forget (non-blocking); failures are logged
but never crash the caller.
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
from typing import Any, Dict, List, Optional

from config.settings import DB_PATH

logger = logging.getLogger(__name__)

# ── Schema ─────────────────────────────────────────────────────────────────────

_DDL = """
-- STT (already created by stt_benchmark; kept here for idempotency)
CREATE TABLE IF NOT EXISTS stt_metrics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT    NOT NULL,
    backend             TEXT    NOT NULL,
    model               TEXT,
    device              TEXT,
    audio_dur_s         REAL,
    latency_ms          REAL,
    cpu_pct             REAL,
    ram_mb              REAL,
    word_count          INTEGER,
    tokens_per_second   REAL,
    transcript          TEXT
);

-- Command pipeline
CREATE TABLE IF NOT EXISTS command_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    raw_input       TEXT,
    action          TEXT,
    success         INTEGER NOT NULL DEFAULT 0,   -- 1 = success
    latency_ms      REAL,
    error_msg       TEXT
);

-- Agent orchestration runs
CREATE TABLE IF NOT EXISTS agent_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    agent_name      TEXT    NOT NULL,
    task_summary    TEXT,
    success         INTEGER NOT NULL DEFAULT 0,
    latency_ms      REAL,
    steps           INTEGER,
    error_msg       TEXT
);

-- OCR / screen-understanding calls
CREATE TABLE IF NOT EXISTS ocr_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    engine          TEXT,
    image_path      TEXT,
    char_count      INTEGER,
    latency_ms      REAL,
    confidence      REAL,
    success         INTEGER NOT NULL DEFAULT 0
);

-- Workflow (macro) replays
CREATE TABLE IF NOT EXISTS workflow_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    workflow_name   TEXT,
    step_count      INTEGER,
    success         INTEGER NOT NULL DEFAULT 0,
    latency_ms      REAL,
    error_msg       TEXT
);
"""


class MetricsStore:
    """Thread-safe SQLite metrics writer and reader."""

    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        self._ensure_schema()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _ensure_schema(self) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.executescript(_DDL)
        except Exception as exc:
            logger.error(f"MetricsStore: schema init failed: {exc}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _now() -> str:
        return datetime.datetime.utcnow().isoformat()

    # ── Write: command ─────────────────────────────────────────────────────────

    def log_command(
        self,
        raw_input: str,
        action: str,
        success: bool,
        latency_ms: float,
        error_msg: str = "",
    ) -> None:
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO command_metrics
                       (timestamp, raw_input, action, success, latency_ms, error_msg)
                       VALUES (?,?,?,?,?,?)""",
                    (self._now(), raw_input, action, int(success), latency_ms, error_msg),
                )
        except Exception as exc:
            logger.error(f"MetricsStore.log_command: {exc}")

    # ── Write: agent ──────────────────────────────────────────────────────────

    def log_agent(
        self,
        agent_name: str,
        task_summary: str,
        success: bool,
        latency_ms: float,
        steps: int = 0,
        error_msg: str = "",
    ) -> None:
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO agent_metrics
                       (timestamp, agent_name, task_summary, success, latency_ms, steps, error_msg)
                       VALUES (?,?,?,?,?,?,?)""",
                    (self._now(), agent_name, task_summary, int(success),
                     latency_ms, steps, error_msg),
                )
        except Exception as exc:
            logger.error(f"MetricsStore.log_agent: {exc}")

    # ── Write: OCR ────────────────────────────────────────────────────────────

    def log_ocr(
        self,
        engine: str,
        image_path: str,
        char_count: int,
        latency_ms: float,
        confidence: float = 0.0,
        success: bool = True,
    ) -> None:
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO ocr_metrics
                       (timestamp, engine, image_path, char_count, latency_ms, confidence, success)
                       VALUES (?,?,?,?,?,?,?)""",
                    (self._now(), engine, image_path, char_count,
                     latency_ms, confidence, int(success)),
                )
        except Exception as exc:
            logger.error(f"MetricsStore.log_ocr: {exc}")

    # ── Write: workflow ───────────────────────────────────────────────────────

    def log_workflow(
        self,
        workflow_name: str,
        step_count: int,
        success: bool,
        latency_ms: float,
        error_msg: str = "",
    ) -> None:
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO workflow_metrics
                       (timestamp, workflow_name, step_count, success, latency_ms, error_msg)
                       VALUES (?,?,?,?,?,?)""",
                    (self._now(), workflow_name, step_count,
                     int(success), latency_ms, error_msg),
                )
        except Exception as exc:
            logger.error(f"MetricsStore.log_workflow: {exc}")

    # ── Read: summary stats ───────────────────────────────────────────────────

    def get_summary(self) -> Dict[str, Any]:
        """Return all KPIs for the dashboard header cards."""
        try:
            with self._conn() as conn:
                def _pct(table: str) -> float:
                    row = conn.execute(
                        f"SELECT COUNT(*) AS tot, SUM(success) AS ok FROM {table}"
                    ).fetchone()
                    tot, ok = row["tot"] or 0, row["ok"] or 0
                    return round((ok / tot * 100), 1) if tot else 0.0

                def _avg_lat(table: str) -> float:
                    row = conn.execute(
                        f"SELECT AVG(latency_ms) AS avg FROM {table}"
                    ).fetchone()
                    return round(row["avg"] or 0, 1)

                stt_row = conn.execute(
                    "SELECT COUNT(*) AS tot, AVG(latency_ms) AS lat, AVG(tokens_per_second) AS tps "
                    "FROM stt_metrics"
                ).fetchone()

                return {
                    "command_success_rate": _pct("command_metrics"),
                    "command_avg_latency_ms": _avg_lat("command_metrics"),
                    "command_count": conn.execute(
                        "SELECT COUNT(*) FROM command_metrics").fetchone()[0],
                    "agent_success_rate": _pct("agent_metrics"),
                    "agent_avg_latency_ms": _avg_lat("agent_metrics"),
                    "agent_count": conn.execute(
                        "SELECT COUNT(*) FROM agent_metrics").fetchone()[0],
                    "ocr_success_rate": _pct("ocr_metrics"),
                    "ocr_avg_latency_ms": _avg_lat("ocr_metrics"),
                    "ocr_count": conn.execute(
                        "SELECT COUNT(*) FROM ocr_metrics").fetchone()[0],
                    "workflow_success_rate": _pct("workflow_metrics"),
                    "workflow_count": conn.execute(
                        "SELECT COUNT(*) FROM workflow_metrics").fetchone()[0],
                    "stt_count": stt_row["tot"] or 0,
                    "stt_avg_latency_ms": round(stt_row["lat"] or 0, 1),
                    "stt_avg_tps": round(stt_row["tps"] or 0, 2),
                }
        except Exception as exc:
            logger.error(f"MetricsStore.get_summary: {exc}")
            return {}

    def get_recent_commands(self, limit: int = 50) -> List[Dict]:
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT timestamp, raw_input, action, success, latency_ms, error_msg "
                    "FROM command_metrics ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.error(f"MetricsStore.get_recent_commands: {exc}")
            return []

    def get_recent_stt(self, limit: int = 50) -> List[Dict]:
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT timestamp, backend, model, latency_ms, word_count, tokens_per_second "
                    "FROM stt_metrics ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.error(f"MetricsStore.get_recent_stt: {exc}")
            return []

    def get_recent_agents(self, limit: int = 50) -> List[Dict]:
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT timestamp, agent_name, task_summary, success, latency_ms, steps "
                    "FROM agent_metrics ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.error(f"MetricsStore.get_recent_agents: {exc}")
            return []

    def get_recent_workflows(self, limit: int = 50) -> List[Dict]:
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT timestamp, workflow_name, step_count, success, latency_ms "
                    "FROM workflow_metrics ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.error(f"MetricsStore.get_recent_workflows: {exc}")
            return []

    def get_daily_command_counts(self, days: int = 7) -> List[Dict]:
        """Return daily success/fail counts for the sparkline chart."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT date(timestamp) AS day,
                           SUM(success)          AS ok,
                           COUNT(*) - SUM(success) AS fail
                    FROM command_metrics
                    WHERE timestamp >= date('now', ?)
                    GROUP BY day ORDER BY day
                    """,
                    (f"-{days} days",),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.error(f"MetricsStore.get_daily_command_counts: {exc}")
            return []

    def get_stt_model_comparison(self) -> List[Dict]:
        """Return avg latency + tps grouped by model for the comparison table."""
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT backend, model,
                           ROUND(AVG(latency_ms), 1) AS avg_latency,
                           ROUND(AVG(tokens_per_second), 2) AS avg_tps,
                           COUNT(*) AS runs
                    FROM stt_metrics
                    GROUP BY backend, model
                    ORDER BY avg_latency
                    """
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.error(f"MetricsStore.get_stt_model_comparison: {exc}")
            return []


# Module-level singleton — import and use directly
_store: Optional[MetricsStore] = None


def get_store() -> MetricsStore:
    """Return the shared MetricsStore instance (lazy-init)."""
    global _store
    if _store is None:
        _store = MetricsStore()
    return _store
