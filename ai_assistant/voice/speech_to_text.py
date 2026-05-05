import speech_recognition as sr
from utils.helpers import setup_logger

logger = setup_logger(__name__)

class SpeechRecognizer:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        # Adjust for ambient noise dynamically
        self.recognizer.dynamic_energy_threshold = True

    def listen(self, timeout=5, phrase_time_limit=10) -> str:
        """Listen to the microphone and convert speech to text."""
        try:
            with sr.Microphone() as source:
                logger.info("Listening...")
                # Reduce noise briefly before listening
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                
                audio = self.recognizer.listen(
                    source, 
                    timeout=timeout, 
                    phrase_time_limit=phrase_time_limit
                )
                
                logger.info("Processing speech...")
                text = self.recognizer.recognize_google(audio)
                return text
                
        except sr.WaitTimeoutError:
            logger.info("Listening timed out.")
            return ""
        except sr.UnknownValueError:
            logger.warning("Could not understand audio.")
            return ""
        except sr.RequestError as e:
            logger.error(f"Could not request results from Google Speech Recognition service; {e}")
            return ""
        except Exception as e:
            logger.error(f"Microphone error: {e}")
            return ""
