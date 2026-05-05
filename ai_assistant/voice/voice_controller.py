import asyncio
from voice.speech_to_text import SpeechRecognizer
from voice.text_to_speech import TextToSpeech
from utils.helpers import setup_logger

logger = setup_logger(__name__)

class VoiceController:
    """Manages the full voice loop: Listen -> Process -> Speak."""
    def __init__(self, command_service=None):
        self.stt = SpeechRecognizer()
        self.tts = TextToSpeech()
        self.command_service = command_service

    def listen(self) -> str:
        return self.stt.listen()

    def speak(self, text: str):
        self.tts.speak(text)

    async def process_voice_async(self, update_chat_callback, status_callback) -> None:
        """Async loop for voice processing."""
        text = await asyncio.to_thread(self.listen)
        
        if text:
            update_chat_callback("You", f"(Voice) {text}")
            status_callback("Processing...")
            
            if self.command_service:
                response = await self.command_service.process_command(text)
                update_chat_callback("Botbro", response)
                status_callback("Ready")
                self.speak(response)
        else:
            status_callback("Ready")
            update_chat_callback("System", "Could not hear or understand audio.")
