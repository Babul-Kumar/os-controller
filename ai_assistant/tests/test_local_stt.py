"""
test_local_stt.py
──────────────────
Unit tests for the Local STT implementation.

Tests
──────
1. test_whisper_model_loads        — WhisperModel initialises without error
2. test_transcribe_wav_file        — transcribes a generated WAV → returns str
3. test_fallback_to_google         — Whisper failure triggers Google fallback
4. test_backend_property           — backend == "whisper" when Whisper is active
5. test_empty_audio_returns_empty  — silence → "" (no crash)
6. test_whisper_without_internet   — offline proof: Whisper works with no network

No microphone is required — all tests use generated or mocked audio.
"""

from __future__ import annotations

import os
import sys
import struct
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Allow imports from ai_assistant/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _write_silent_wav(path: str, duration_s: float = 1.0, sample_rate: int = 16_000) -> None:
    """Write a minimal silent PCM WAV file (16-bit, mono)."""
    n_samples = int(duration_s * sample_rate)
    data_chunk = struct.pack(f"<{n_samples}h", *([0] * n_samples))
    with open(path, "wb") as f:
        # RIFF header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + len(data_chunk)))
        f.write(b"WAVE")
        # fmt chunk
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))        # chunk size
        f.write(struct.pack("<H", 1))         # PCM
        f.write(struct.pack("<H", 1))         # mono
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", sample_rate * 2))  # byte rate
        f.write(struct.pack("<H", 2))         # block align
        f.write(struct.pack("<H", 16))        # bits per sample
        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", len(data_chunk)))
        f.write(data_chunk)


# ── Test 1: Model loads ────────────────────────────────────────────────────────

class TestWhisperModelLoads(unittest.TestCase):
    """WhisperSTT initialises without raising even if model is not cached."""

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("faster_whisper") is not None,
        "faster-whisper not installed",
    )
    def test_whisper_model_loads(self):
        from voice.local_speech_to_text import WhisperSTT
        # Use tiny.en to keep test fast; real install uses distil-small.en
        engine = WhisperSTT(model_name="tiny.en", device="cpu", compute_type="int8")
        self.assertIsNotNone(engine, "WhisperSTT instance should not be None")
        self.assertEqual(engine.get_backend(), "whisper")


# ── Test 2: Transcribe WAV file ────────────────────────────────────────────────

class TestTranscribeWavFile(unittest.TestCase):
    """transcribe() returns a string (may be empty) for any valid WAV."""

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("faster_whisper") is not None,
        "faster-whisper not installed",
    )
    def test_transcribe_wav_returns_string(self):
        from voice.local_speech_to_text import WhisperSTT
        engine = WhisperSTT(model_name="tiny.en", device="cpu", compute_type="int8")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            _write_silent_wav(tmp.name, duration_s=1.0)
            wav_path = tmp.name

        try:
            result = engine.transcribe(wav_path)
            self.assertIsInstance(result, str, "transcribe() must return a string")
        finally:
            os.unlink(wav_path)


# ── Test 3: Fallback to Google ─────────────────────────────────────────────────

class TestFallbackToGoogle(unittest.TestCase):
    """When WhisperSTT fails, SpeechRecognizer falls back to GoogleSTT."""

    def test_fallback_triggered_on_whisper_error(self):
        """Patch WhisperSTT.listen to raise; GoogleSTT.listen should be called."""

        # Mock both engines
        mock_whisper = MagicMock()
        mock_whisper.get_backend.return_value = "whisper"
        mock_whisper.last_error = "simulated failure"
        mock_whisper.listen.side_effect = RuntimeError("Simulated Whisper failure")

        mock_google = MagicMock()
        mock_google.get_backend.return_value = "google"
        mock_google.last_error = ""
        mock_google.listen.return_value = "open chrome"

        with patch("voice.speech_to_text.SpeechRecognizer._init_engines") as mock_init:
            from voice.speech_to_text import SpeechRecognizer
            recognizer = SpeechRecognizer.__new__(SpeechRecognizer)
            recognizer.last_error = ""
            recognizer._primary = mock_whisper
            recognizer._fallback = mock_google

            result = recognizer.listen()

        mock_google.listen.assert_called_once()
        self.assertEqual(result, "open chrome")


# ── Test 4: Backend property ───────────────────────────────────────────────────

class TestBackendProperty(unittest.TestCase):
    """SpeechRecognizer.backend returns the primary engine's identifier."""

    def test_backend_is_whisper_when_primary_set(self):
        mock_engine = MagicMock()
        mock_engine.get_backend.return_value = "whisper"

        from voice.speech_to_text import SpeechRecognizer
        recognizer = SpeechRecognizer.__new__(SpeechRecognizer)
        recognizer.last_error = ""
        recognizer._primary = mock_engine
        recognizer._fallback = None

        self.assertEqual(recognizer.backend, "whisper")

    def test_backend_is_google_when_primary_none(self):
        mock_engine = MagicMock()
        mock_engine.get_backend.return_value = "google"

        from voice.speech_to_text import SpeechRecognizer
        recognizer = SpeechRecognizer.__new__(SpeechRecognizer)
        recognizer.last_error = ""
        recognizer._primary = None
        recognizer._fallback = mock_engine

        self.assertEqual(recognizer.backend, "google")


# ── Test 5: Empty / silent audio ──────────────────────────────────────────────

class TestEmptyAudioReturnsEmpty(unittest.TestCase):
    """Silent WAV should return "" without raising an exception."""

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("faster_whisper") is not None,
        "faster-whisper not installed",
    )
    def test_silent_wav_returns_empty_string(self):
        from voice.local_speech_to_text import WhisperSTT
        engine = WhisperSTT(model_name="tiny.en", device="cpu", compute_type="int8")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            _write_silent_wav(tmp.name, duration_s=0.5)
            wav_path = tmp.name

        try:
            result = engine.transcribe(wav_path)
            # Silent audio should produce empty or whitespace-only transcript
            self.assertIsInstance(result, str)
            self.assertEqual(result.strip(), "")
        finally:
            os.unlink(wav_path)


# ── Test 6: Offline verification ──────────────────────────────────────────────

class TestWhisperWithoutInternet(unittest.TestCase):
    """Prove that Whisper works offline — main selling point of this feature.

    Strategy: patch socket.getaddrinfo to simulate no internet; verify that
    WhisperSTT.transcribe() still succeeds (already-loaded model needs no net).
    """

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("faster_whisper") is not None,
        "faster-whisper not installed",
    )
    def test_whisper_works_without_internet(self):
        import socket
        from voice.local_speech_to_text import WhisperSTT

        engine = WhisperSTT(model_name="tiny.en", device="cpu", compute_type="int8")
        if engine._model is None:
            self.skipTest("Whisper model could not be loaded — skipping offline test.")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            _write_silent_wav(tmp.name, duration_s=1.0)
            wav_path = tmp.name

        def _no_internet(*args, **kwargs):
            raise OSError("Simulated: no network")

        try:
            original_getaddrinfo = socket.getaddrinfo
            socket.getaddrinfo = _no_internet

            result = engine.transcribe(wav_path)

            # Transcription must not raise and must return a string
            self.assertIsInstance(result, str, "Result must be a string even offline")
            # Backend must still be whisper
            self.assertEqual(engine.get_backend(), "whisper")
        finally:
            socket.getaddrinfo = original_getaddrinfo
            os.unlink(wav_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
