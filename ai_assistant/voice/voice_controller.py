"""
voice_controller.py  (updated)
───────────────────────────────
Manages the full voice loop: Listen → Process → Speak.

Changes vs previous version
────────────────────────────
• Logs the active STT backend on init (whisper / google / none)
• Exposes a ``backend`` property so the GUI can display current engine
• Passes metrics to callers if they want them (``get_stt_metrics()``)
"""

from __future__ import annotations

import asyncio
import logging

from voice.speech_to_text import SpeechRecognizer
from voice.text_to_speech import TextToSpeech
from utils.helpers import setup_logger

logger = setup_logger(__name__)


class VoiceController:
    """Manages the full voice loop: Listen → Process → Speak."""

    def __init__(self, command_service=None) -> None:
        self.stt = SpeechRecognizer()
        self.tts = TextToSpeech()
        self.command_service = command_service

        # Report which STT backend was selected
        logger.info(f"VoiceController ready — STT backend: [{self.stt.backend.upper()}]")

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def backend(self) -> str:
        """Active STT backend name: 'whisper' | 'google' | 'none'."""
        return self.stt.backend

    # ── Core methods ──────────────────────────────────────────────────────────

    def listen(self) -> str:
        return self.stt.listen()

    def speak(self, text: str) -> None:
        self.tts.speak(text)

    def shutdown(self) -> None:
        self.tts.shutdown()

    def get_stt_metrics(self) -> dict:
        """Return performance metrics from the last transcription call."""
        return self.stt.get_metrics()

    # ── Async voice loop ──────────────────────────────────────────────────────

    async def process_voice_async(self, update_chat_callback, status_callback) -> None:
        """Async loop for voice processing."""
        try:
            text = await asyncio.to_thread(self.listen)

            if text:
                update_chat_callback("You", f"(Voice) {text}")
                status_callback("Processing…")

                if self.command_service:
                    response = await self.command_service.process_command(text)
                    update_chat_callback("Botbro", response)
                    self.speak(response)
                return

            error_message = self.stt.get_last_error()
            if error_message:
                update_chat_callback("System", f"Voice input unavailable: {error_message}")
            else:
                update_chat_callback("System", "Could not hear or understand audio.")

        except Exception as exc:
            logger.error(f"Voice pipeline error: {exc}")
            update_chat_callback("System", f"Voice pipeline error: {exc}")
        finally:
            status_callback("Ready")
