import queue
import threading
from typing import Optional

import pyttsx3

from config.settings import VOICE_RATE, VOICE_VOLUME
from utils.helpers import setup_logger

logger = setup_logger(__name__)


class TextToSpeech:
    def __init__(self):
        self.engine: Optional[pyttsx3.Engine] = None
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._stop_event = threading.Event()
        self._engine_ready = threading.Event()
        self._worker = threading.Thread(
            target=self._run_worker,
            name="TextToSpeechWorker",
            daemon=True,
        )
        self._worker.start()
        self._engine_ready.wait(timeout=5)

    def _configure_engine(self) -> pyttsx3.Engine:
        engine = pyttsx3.init()
        engine.setProperty("rate", VOICE_RATE)
        engine.setProperty("volume", VOICE_VOLUME)

        # Prefer a female voice when one is available.
        voices = engine.getProperty("voices")
        for voice in voices:
            name = getattr(voice, "name", "").lower()
            if "zira" in name or "female" in name:
                engine.setProperty("voice", voice.id)
                break

        return engine

    def _run_worker(self):
        try:
            self.engine = self._configure_engine()
        except Exception as exc:
            logger.error(f"Failed to initialize pyttsx3: {exc}")
            self.engine = None
        finally:
            self._engine_ready.set()

        while not self._stop_event.is_set():
            try:
                text = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if text is None:
                self._queue.task_done()
                break

            if self.engine is None:
                self._queue.task_done()
                continue

            try:
                self.engine.say(text)
                self.engine.runAndWait()
            except Exception as exc:
                logger.error(f"Speech error: {exc}")
            finally:
                self._queue.task_done()

        if self.engine is not None:
            try:
                self.engine.stop()
            except Exception as exc:
                logger.debug(f"TTS engine stop failed: {exc}")

    def speak(self, text: str):
        """Queue speech on the dedicated TTS thread."""
        if not text:
            return

        logger.info(f"Speaking: {text}")
        self._engine_ready.wait(timeout=5)
        self._queue.put(text)

    def shutdown(self):
        """Stop the speech worker cleanly during app shutdown."""
        if self._stop_event.is_set():
            return

        self._stop_event.set()
        self._queue.put(None)
        self._worker.join(timeout=2)
