import sys
import threading
import asyncio
from PyQt5.QtWidgets import QApplication

from gui.app_ui import BotbroGUI
from services.command_service import CommandService
from voice.voice_controller import VoiceController
from utils.helpers import setup_logger

logger = setup_logger("main")

class BotbroApp:
    def __init__(self):
        # Create an asyncio event loop for background tasks
        self.loop = asyncio.new_event_loop()
        self.async_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.async_thread.start()

        # Initialize Services
        self.command_service = CommandService()
        self.voice_controller = VoiceController(command_service=self.command_service)
        
        # Init GUI last as it requires callbacks
        self.app = QApplication(sys.argv)
        self.gui = BotbroGUI(
            process_callback=self.process_text_input,
            voice_callback=self.process_voice_input
        )

    def _run_async_loop(self):
        """Run the asyncio event loop in a background thread."""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def process_text_input(self, text: str):
        """Handle text input from the GUI."""
        logger.info(f"User text input: {text}")
        asyncio.run_coroutine_threadsafe(self._process_text_async(text), self.loop)

    async def _process_text_async(self, text: str):
        """Process text asynchronously and update GUI safely."""
        try:
            response = await self.command_service.process_command(text)
            self.gui.signals.update_chat.emit("Botbro", response)
            self.gui.signals.status_update.emit("Ready")
            self.voice_controller.speak(response)
        except Exception as e:
            logger.error(f"Text pipeline error: {e}")
            self.gui.signals.update_chat.emit("System", f"Pipeline error: {str(e)}")
            self.gui.signals.status_update.emit("Ready")

    def process_voice_input(self):
        """Handle voice input from the GUI."""
        # Use run_coroutine_threadsafe to run the async voice loop
        
        def update_chat(sender, msg):
            self.gui.signals.update_chat.emit(sender, msg)
            
        def status_update(status):
            self.gui.signals.status_update.emit(status)
            if status == "Ready" or status.startswith("System"):
                # Ensure buttons are re-enabled
                self.gui.voice_btn.setEnabled(True)
                self.gui.text_input.setEnabled(True)
                
        asyncio.run_coroutine_threadsafe(
            self.voice_controller.process_voice_async(update_chat, status_update), 
            self.loop
        )

    def run(self):
        """Start the application."""
        logger.info("Starting Botbro App...")
        self.gui.show()
        
        # Initial greeting
        greeting = "Hello, I am Botbro. How can I assist you today?"
        self.gui.signals.update_chat.emit("Botbro", greeting)
        self.voice_controller.speak(greeting)
        
        sys.exit(self.app.exec_())

if __name__ == "__main__":
    assistant = BotbroApp()
    assistant.run()
