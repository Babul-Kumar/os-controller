"""
stt_engine.py
─────────────
Abstract base class for Speech-To-Text engines.

All concrete STT backends (WhisperSTT, GoogleSTT, VoskSTT, …) inherit from
this class and implement `transcribe()`.  This keeps VoiceController decoupled
from any specific library — future upgrades require zero changes upstream.

Interface contract
──────────────────
  engine = WhisperSTT()          # or GoogleSTT(), VoskSTT(), …
  text   = engine.transcribe(audio_path)
  name   = engine.get_backend()  # "whisper" | "google" | "vosk" …
  stats  = engine.get_metrics()  # dict with timing / memory data
"""

from __future__ import annotations

import abc
import time
from typing import Dict, Any


class STTEngine(abc.ABC):
    """Abstract Speech-To-Text engine.

    Subclasses MUST implement:
        transcribe(audio_path: str) -> str

    Subclasses MAY override:
        get_backend() -> str          — human-readable backend name
        get_metrics() -> Dict         — last-call performance stats
        is_available() -> bool        — returns False if dependencies missing
    """

    def __init__(self) -> None:
        self.last_error: str = ""
        self._last_metrics: Dict[str, Any] = {}

    # ── Required ──────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def transcribe(self, audio_path: str) -> str:
        """Transcribe a WAV file and return the recognised text.

        Args:
            audio_path: Absolute path to a 16 kHz, mono WAV file.

        Returns:
            Recognised text string, or "" on failure / silence.
        """

    # ── Optional overrides ────────────────────────────────────────────────────

    def get_backend(self) -> str:
        """Return a short identifier for the active backend."""
        return self.__class__.__name__.replace("STT", "").lower()

    def get_metrics(self) -> Dict[str, Any]:
        """Return performance stats from the most recent transcribe() call."""
        return dict(self._last_metrics)

    @classmethod
    def is_available(cls) -> bool:
        """Return True if this engine's dependencies are installed.

        Override in subclasses to do real import checks.
        """
        return True

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _timed_transcribe(self, audio_path: str) -> tuple[str, float]:
        """Run transcribe() and return (text, elapsed_seconds).

        Used internally by subclasses that want timing without boilerplate.
        """
        t0 = time.perf_counter()
        text = self.transcribe(audio_path)
        elapsed = time.perf_counter() - t0
        return text, elapsed
