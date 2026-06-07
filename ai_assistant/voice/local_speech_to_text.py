"""
local_speech_to_text.py
───────────────────────
WhisperSTT — a fully local, offline Speech-To-Text engine powered by
faster-whisper (CTranslate2 backend).

GPU auto-detection priority
────────────────────────────
1. STT_DEVICE / STT_COMPUTE from config/settings.py  (user override)
2. torch.cuda.is_available()                          (auto-detect)
3. CPU + int8                                          (safe fallback)

Model default: distil-small.en
• Fast inference   (~2-4× real-time on CPU)
• Good accuracy for command-oriented speech
• Small footprint  (~166 MB, cached after first download)
"""

from __future__ import annotations

import os
import tempfile
import time
import logging
import psutil
from typing import Optional

from voice.stt_engine import STTEngine

logger = logging.getLogger(__name__)

# ── Lazy imports — graceful if packages are missing ───────────────────────────

try:
    import sounddevice as sd
    import soundfile as sf
    _AUDIO_AVAILABLE = True
except ImportError:
    _AUDIO_AVAILABLE = False
    logger.warning("sounddevice/soundfile not installed — mic capture disabled.")

try:
    from faster_whisper import WhisperModel
    _WHISPER_AVAILABLE = True
except ImportError:
    _WHISPER_AVAILABLE = False
    logger.warning("faster-whisper not installed — WhisperSTT unavailable.")


def _resolve_device() -> tuple[str, str]:
    """Return (device, compute_type) using the 3-level priority chain."""
    # Import settings lazily to avoid circular imports during testing
    try:
        from config.settings import STT_DEVICE, STT_COMPUTE
        if STT_DEVICE:   # User explicitly set a value (non-empty string)
            logger.info(f"STT: Using user-configured device={STT_DEVICE}, compute={STT_COMPUTE}")
            return STT_DEVICE, STT_COMPUTE
    except ImportError:
        pass

    # Auto-detect GPU
    try:
        import torch
        if torch.cuda.is_available():
            logger.info("STT: CUDA detected — using GPU (float16)")
            return "cuda", "float16"
    except ImportError:
        pass

    # Safe CPU fallback
    logger.info("STT: Using CPU (int8)")
    return "cpu", "int8"


class WhisperSTT(STTEngine):
    """Local offline STT using faster-whisper.

    Args:
        model_name:   Whisper / Distil-Whisper model identifier.
                      Default: ``distil-small.en``
        device:       Override device (``"cpu"`` | ``"cuda"``).
                      ``None`` triggers auto-detection.
        compute_type: Override compute type.  ``None`` triggers auto-detection.
        language:     Force transcription language (speeds up decoding).
        beam_size:    Beam search width (higher = more accurate, slower).
        sample_rate:  Microphone sample rate in Hz.
        record_secs:  Default recording duration when using ``listen()``.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        language: Optional[str] = None,
        beam_size: Optional[int] = None,
        sample_rate: int = 16_000,
        record_secs: float = 10.0,
    ) -> None:
        super().__init__()

        # Pull defaults from settings, allow constructor to override
        try:
            from config.settings import (
                STT_MODEL, STT_LANGUAGE, STT_BEAM_SIZE
            )
        except ImportError:
            STT_MODEL, STT_LANGUAGE, STT_BEAM_SIZE = "distil-small.en", "en", 5

        self.model_name  = model_name  or STT_MODEL
        self.language    = language    or STT_LANGUAGE
        self.beam_size   = beam_size   if beam_size is not None else STT_BEAM_SIZE
        self.sample_rate = sample_rate
        self.record_secs = record_secs

        # Resolve device
        auto_device, auto_compute = _resolve_device()
        self._device       = device       or auto_device
        self._compute_type = compute_type or auto_compute

        self._model: Optional["WhisperModel"] = None
        self._load_model()

    # ── Model loading ──────────────────────────────────────────────────────────

    def _load_model(self) -> None:
        if not _WHISPER_AVAILABLE:
            self.last_error = "faster-whisper is not installed."
            return
        try:
            logger.info(
                f"Loading Whisper model '{self.model_name}' "
                f"on {self._device} ({self._compute_type}) …"
            )
            self._model = WhisperModel(
                self.model_name,
                device=self._device,
                compute_type=self._compute_type,
            )
            logger.info("Whisper model loaded successfully.")
        except Exception as exc:
            self.last_error = str(exc)
            logger.error(f"Failed to load Whisper model: {exc}")
            self._model = None

    # ── STTEngine interface ───────────────────────────────────────────────────

    @classmethod
    def is_available(cls) -> bool:
        return _WHISPER_AVAILABLE and _AUDIO_AVAILABLE

    def get_backend(self) -> str:
        return "whisper"

    def transcribe(self, audio_path: str) -> str:
        """Transcribe a WAV file and return recognised text.

        Populates ``self._last_metrics`` with timing, CPU, RAM, and token stats.
        """
        if self._model is None:
            self.last_error = "Whisper model not loaded."
            return ""

        self.last_error = ""
        proc = psutil.Process(os.getpid())
        cpu_before = proc.cpu_percent(interval=None)
        ram_before = proc.memory_info().rss / 1_048_576  # MB

        try:
            # Measure audio duration
            with sf.SoundFile(audio_path) as f:
                audio_dur_s = len(f) / f.samplerate
        except Exception:
            audio_dur_s = 0.0

        t0 = time.perf_counter()
        try:
            segments, _info = self._model.transcribe(
                audio_path,
                language=self.language,
                beam_size=self.beam_size,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
        except Exception as exc:
            self.last_error = str(exc)
            logger.error(f"Whisper transcription error: {exc}")
            return ""
        finally:
            elapsed_s = time.perf_counter() - t0

        cpu_after = proc.cpu_percent(interval=None)
        ram_after = proc.memory_info().rss / 1_048_576

        word_count = len(text.split()) if text else 0
        tokens_per_second = round(word_count / elapsed_s, 2) if elapsed_s > 0 else 0.0

        self._last_metrics = {
            "backend":      "whisper",
            "model":        self.model_name,
            "device":       self._device,
            "audio_dur_s":  round(audio_dur_s, 3),
            "latency_ms":   round(elapsed_s * 1000, 1),
            "cpu_pct":      round((cpu_before + cpu_after) / 2, 1),
            "ram_mb":       round((ram_before + ram_after) / 2, 1),
            "word_count":   word_count,
            "tokens_per_second": tokens_per_second,
            "transcript":   text,
        }
        logger.info(
            f"Whisper transcribed {word_count} words in {elapsed_s*1000:.0f} ms "
            f"({tokens_per_second} tps)"
        )
        return text

    # ── Microphone capture ────────────────────────────────────────────────────

    def listen(
        self,
        timeout: float = 5.0,
        phrase_time_limit: float = 10.0,
    ) -> str:
        """Record from mic and transcribe.  Returns text or "".

        Args:
            timeout:           Seconds to wait for speech to begin (unused —
                               kept for interface parity with SpeechRecognizer).
            phrase_time_limit: Maximum seconds to record.
        """
        if not _AUDIO_AVAILABLE:
            self.last_error = "sounddevice is not installed."
            return ""
        if self._model is None:
            self.last_error = "Whisper model not loaded."
            return ""

        duration = min(phrase_time_limit, self.record_secs)
        logger.info(f"Recording {duration}s of audio at {self.sample_rate} Hz …")

        try:
            recording = sd.rec(
                int(duration * self.sample_rate),
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
            )
            sd.wait()
        except Exception as exc:
            self.last_error = str(exc)
            logger.error(f"Microphone error: {exc}")
            return ""

        # Write to temp WAV so Whisper can read it
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            sf.write(tmp_path, recording, self.sample_rate)
            return self.transcribe(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
