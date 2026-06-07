"""
stt_benchmark.py
─────────────────
Standalone benchmark tool for comparing STT engines.

Usage
─────
  python utils/stt_benchmark.py                  # record from mic
  python utils/stt_benchmark.py --file audio.wav # transcribe a file
  python utils/stt_benchmark.py --runs 3         # repeat N times

Output
──────
  ┌─────────────────┬────────────┬──────────┬──────────┬──────────┬───────┬──────────┐
  │ Backend         │ Latency ms │ CPU %    │ RAM MB   │ TPS      │ Words │ Duration │
  ├─────────────────┼────────────┼──────────┼──────────┼──────────┼───────┼──────────┤
  │ whisper         │ 1240       │ 45.2     │ 412      │ 28.5     │ 8     │ 3.1s     │
  └─────────────────┴────────────┴──────────┴──────────┴──────────┴───────┴──────────┘

Results are stored in memory.db → stt_metrics table.
This seeds the future Performance Dashboard.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sqlite3
import sys
import tempfile
import time

# Allow running from the ai_assistant/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DB_PATH


# ── DB schema ─────────────────────────────────────────────────────────────────

CREATE_TABLE = """
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
"""


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_TABLE)
    conn.commit()


def save_metrics(conn: sqlite3.Connection, metrics: dict) -> None:
    conn.execute(
        """
        INSERT INTO stt_metrics
            (timestamp, backend, model, device, audio_dur_s,
             latency_ms, cpu_pct, ram_mb, word_count, tokens_per_second, transcript)
        VALUES
            (:timestamp, :backend, :model, :device, :audio_dur_s,
             :latency_ms, :cpu_pct, :ram_mb, :word_count, :tokens_per_second, :transcript)
        """,
        metrics,
    )
    conn.commit()


# ── Benchmark runner ──────────────────────────────────────────────────────────

def run_benchmark(audio_path: str | None, runs: int) -> None:
    """Run N transcriptions and print + persist results."""

    # Build engines to test
    engines: list[tuple[str, object]] = []

    try:
        from voice.local_speech_to_text import WhisperSTT
        if WhisperSTT.is_available():
            engines.append(("WhisperSTT", WhisperSTT()))
        else:
            print("[warn] faster-whisper not installed — skipping WhisperSTT.")
    except Exception as exc:
        print(f"[warn] WhisperSTT unavailable: {exc}")

    try:
        from voice.google_speech_to_text import GoogleSTT
        if GoogleSTT.is_available():
            engines.append(("GoogleSTT", GoogleSTT()))
        else:
            print("[warn] SpeechRecognition not installed — skipping GoogleSTT.")
    except Exception as exc:
        print(f"[warn] GoogleSTT unavailable: {exc}")

    if not engines:
        print("[error] No STT engines available to benchmark.")
        return

    # Prepare audio
    tmp_file = None
    if audio_path is None:
        print("Recording 5 seconds from microphone …")
        try:
            import sounddevice as sd
            import soundfile as sf
            recording = sd.rec(5 * 16_000, samplerate=16_000, channels=1, dtype="float32")
            sd.wait()
            tmp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            sf.write(tmp_file.name, recording, 16_000)
            audio_path = tmp_file.name
            print(f"Audio saved to: {audio_path}")
        except ImportError:
            print("[error] sounddevice/soundfile required for mic recording.")
            return

    # Connect to DB
    conn = sqlite3.connect(DB_PATH)
    ensure_table(conn)

    # Table header
    cols = ["Backend", "Run", "Latency ms", "CPU %", "RAM MB", "TPS", "Words", "Dur s"]
    col_w = [18, 4, 10, 8, 8, 8, 6, 6]
    sep = "┼".join("─" * w for w in col_w)
    header = "│".join(f" {c:<{col_w[i]-1}}" for i, c in enumerate(cols))
    print()
    print("┌" + "┬".join("─" * w for w in col_w) + "┐")
    print("│" + header + "│")
    print("├" + sep + "┤")

    for name, engine in engines:
        for run in range(1, runs + 1):
            text = engine.transcribe(audio_path)
            m = engine.get_metrics()
            if not m:
                print(f"│ {name:<17}│ {run:>3} │ (no metrics)       │")
                continue

            row_vals = [
                name,
                str(run),
                str(m.get("latency_ms", "")),
                str(m.get("cpu_pct", "")),
                str(m.get("ram_mb", "")),
                str(m.get("tokens_per_second", "")),
                str(m.get("word_count", "")),
                str(m.get("audio_dur_s", "")),
            ]
            row = "│".join(f" {v:<{col_w[i]-1}}" for i, v in enumerate(row_vals))
            print("│" + row + "│")

            # Persist
            record = {
                "timestamp":         datetime.datetime.utcnow().isoformat(),
                "backend":           m.get("backend", name),
                "model":             m.get("model", ""),
                "device":            m.get("device", ""),
                "audio_dur_s":       m.get("audio_dur_s"),
                "latency_ms":        m.get("latency_ms"),
                "cpu_pct":           m.get("cpu_pct"),
                "ram_mb":            m.get("ram_mb"),
                "word_count":        m.get("word_count"),
                "tokens_per_second": m.get("tokens_per_second"),
                "transcript":        m.get("transcript", text),
            }
            save_metrics(conn, record)

    print("└" + "┴".join("─" * w for w in col_w) + "┘")
    print(f"\nResults saved to: {DB_PATH} (table: stt_metrics)\n")

    conn.close()
    if tmp_file is not None:
        try:
            os.unlink(tmp_file.name)
        except OSError:
            pass


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Botbro STT Benchmark")
    parser.add_argument("--file", help="Path to WAV file (default: record from mic)")
    parser.add_argument("--runs", type=int, default=1, help="Number of runs per engine")
    args = parser.parse_args()
    run_benchmark(audio_path=args.file, runs=args.runs)


if __name__ == "__main__":
    main()
