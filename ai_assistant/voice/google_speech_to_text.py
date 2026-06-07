"""
google_speech_to_text.py
─────────────────────────
GoogleSTT — cloud-based fallback engine wrapping the SpeechRecognition library.

This adapter conforms to the STTEngine interface so VoiceController can treat
it identically to WhisperSTT.  It requires an active internet connection.
"""

from __future__ import annotations

import io
import logging
import os
import time
import psutil

import speech_recognition as sr

from voice.stt_engine import STTEngine

logger = logging.getLogger(__name__)


class GoogleSTT(STTEngine):
    """Cloud STT using Google Web Speech API via SpeechRecognition.

    Falls back to returning "" on network errors, so callers can handle
    gracefully without crashing the voice pipeline.
    """

    def __init__(self, timeout: float = 5.0, phrase_time_limit: float = 10.0) -> None:
        super().__init__()
        self._recognizer = sr.Recognizer()
        self._recognizer.dynamic_energy_threshold = True
        self._timeout = timeout
        self._phrase_time_limit = phrase_time_limit

    # ── STTEngine interface ───────────────────────────────────────────────────

    @classmethod
    def is_available(cls) -> bool:
        try:
            import speech_recognition  # noqa: F401
            return True
        except ImportError:
            return False

    def get_backend(self) -> str:
        return "google"

    def transcribe(self, audio_path: str) -> str:
        """Transcribe a WAV file using Google Web Speech API.

        Populates ``self._last_metrics`` with timing and basic stats.
        """
        self.last_error = ""
        proc = psutil.Process(os.getpid())
        ram_before = proc.memory_info().rss / 1_048_576

        t0 = time.perf_counter()
        try:
            with sr.AudioFile(audio_path) as source:
                audio_data = self._recognizer.record(source)
            text = self._recognizer.recognize_google(audio_data)
        except sr.UnknownValueError:
            logger.warning("Google STT: could not understand audio.")
            text = ""
        except sr.RequestError as exc:
            self.last_error = f"Google STT service unavailable: {exc}"
            logger.error(self.last_error)
            text = ""
        except Exception as exc:
            self.last_error = str(exc)
            logger.error(f"Google STT error: {exc}")
            text = ""
        finally:
            elapsed_s = time.perf_counter() - t0

        ram_after = proc.memory_info().rss / 1_048_576
        word_count = len(text.split()) if text else 0
        tokens_per_second = round(word_count / elapsed_s, 2) if elapsed_s > 0 else 0.0

        self._last_metrics = {
            "backend":           "google",
            "latency_ms":        round(elapsed_s * 1000, 1),
            "ram_mb":            round((ram_before + ram_after) / 2, 1),
            "word_count":        word_count,
            "tokens_per_second": tokens_per_second,
            "transcript":        text,
        }
        return text

    # ── Microphone capture ────────────────────────────────────────────────────

    def listen(self, timeout: float = 5.0, phrase_time_limit: float = 10.0) -> str:
        """Listen from microphone and transcribe using Google STT."""
        self.last_error = ""
        try:
            with sr.Microphone() as source:
                logger.info("Google STT: listening …")
                self._recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self._recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
            text = self._recognizer.recognize_google(audio)
            return text

        except sr.WaitTimeoutError:
            logger.info("Google STT: listening timed out.")
            return ""
        except sr.UnknownValueError:
            logger.warning("Google STT: could not understand audio.")
            return ""
        except sr.RequestError as exc:
            self.last_error = "Speech recognition service is unavailable right now."
            logger.error(f"Google STT request error: {exc}")
            return ""
        except Exception as exc:
            self.last_error = str(exc)
            logger.error(f"Google STT microphone error: {exc}")
            return ""
