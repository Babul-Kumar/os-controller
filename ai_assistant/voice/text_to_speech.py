import pyttsx3
import threading
from config.settings import VOICE_RATE, VOICE_VOLUME
from utils.helpers import setup_logger

logger = setup_logger(__name__)

class TextToSpeech:
    def __init__(self):
        try:
            self.engine = pyttsx3.init()
            self.engine.setProperty('rate', VOICE_RATE)
            self.engine.setProperty('volume', VOICE_VOLUME)
            
            # Use female voice if available
            voices = self.engine.getProperty('voices')
            for voice in voices:
                if 'zira' in voice.name.lower() or 'female' in voice.name.lower():
                    self.engine.setProperty('voice', voice.id)
                    break
        except Exception as e:
            logger.error(f"Failed to initialize pyttsx3: {e}")
            self.engine = None

    def _speak_sync(self, text: str):
        if self.engine:
            try:
                self.engine.say(text)
                self.engine.runAndWait()
            except Exception as e:
                logger.error(f"Speech error: {e}")

    def speak(self, text: str):
        """Speak the text asynchronously so it doesn't block the UI."""
        logger.info(f"Speaking: {text}")
        thread = threading.Thread(target=self._speak_sync, args=(text,))
        thread.daemon = True
        thread.start()
