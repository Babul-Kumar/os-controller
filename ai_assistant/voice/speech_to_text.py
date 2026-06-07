"""
speech_to_text.py  (updated)
────────────────────────────
SpeechRecognizer — unified STT entry point with a 3-level fallback chain.

Priority chain
──────────────
  1. WhisperSTT (local, offline, faster-whisper)
     ↓ ImportError / model load failure
  2. GoogleSTT  (cloud, online, speech_recognition)
     ↓ network error / unavailable
  3. Return ""  (silent failure — caller handles gracefully)

VoiceController should always use this class rather than the concrete engines
directly, so the fallback behaviour is always in effect.
"""

from __future__ import annotations

import logging
from typing import Optional

from utils.helpers import setup_logger

logger = setup_logger(__name__)


class SpeechRecognizer:
    """Unified STT facade with automatic engine selection and fallback."""

    def __init__(self) -> None:
        self._primary: Optional[object] = None    # WhisperSTT instance
        self._fallback: Optional[object] = None   # GoogleSTT instance
        self.last_error: str = ""

        self._init_engines()

    # ── Engine initialisation ─────────────────────────────────────────────────

    def _init_engines(self) -> None:
        """Attempt to load WhisperSTT; always load GoogleSTT as backup."""

        # Primary: local Whisper
        try:
            from voice.local_speech_to_text import WhisperSTT
            if WhisperSTT.is_available():
                self._primary = WhisperSTT()
                logger.info("STT primary engine: WhisperSTT (local/offline)")
            else:
                logger.warning("faster-whisper not available — skipping WhisperSTT.")
        except Exception as exc:
            logger.warning(f"WhisperSTT could not be loaded: {exc}")
            self._primary = None

        # Fallback: Google cloud
        try:
            from voice.google_speech_to_text import GoogleSTT
            if GoogleSTT.is_available():
                self._fallback = GoogleSTT()
                logger.info("STT fallback engine: GoogleSTT (cloud)")
            else:
                logger.warning("SpeechRecognition not available — Google fallback disabled.")
        except Exception as exc:
            logger.warning(f"GoogleSTT could not be loaded: {exc}")
            self._fallback = None

        if self._primary is None and self._fallback is None:
            logger.error("No STT engine available — voice input will be disabled.")

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def backend(self) -> str:
        """Name of the currently active primary backend."""
        if self._primary is not None:
            return self._primary.get_backend()
        if self._fallback is not None:
            return self._fallback.get_backend()
        return "none"

    def listen(self, timeout: float = 5.0, phrase_time_limit: float = 10.0) -> str:
        """Listen from the microphone and return transcribed text.

        Tries WhisperSTT first; falls back to GoogleSTT on any failure.
        Returns "" if both engines fail.
        """
        self.last_error = ""

        # ── Try primary (Whisper) ──────────────────────────────────────────
        if self._primary is not None:
            try:
                text = self._primary.listen(
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
                if text:
                    return text
                # Empty result — check for hard error before falling back
                if self._primary.last_error:
                    logger.warning(
                        f"WhisperSTT error ('{self._primary.last_error}') "
                        "— falling back to GoogleSTT."
                    )
            except Exception as exc:
                logger.warning(f"WhisperSTT raised an exception: {exc} — trying Google fallback.")

        # ── Fallback (Google) ─────────────────────────────────────────────
        if self._fallback is not None:
            try:
                text = self._fallback.listen(
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
                if text:
                    logger.info("Google STT fallback produced a result.")
                return text
            except Exception as exc:
                self.last_error = str(exc)
                logger.error(f"GoogleSTT fallback also failed: {exc}")

        return ""

    def get_last_error(self) -> str:
        return self.last_error

    def get_metrics(self) -> dict:
        """Return performance metrics from the most-recently-used engine."""
        if self._primary is not None and hasattr(self._primary, "get_metrics"):
            return self._primary.get_metrics()
        return {}
