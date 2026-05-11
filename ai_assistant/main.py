import asyncio
import os
import signal
import sys
import threading
from concurrent.futures import Future

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from gui.main_window import BotbroGUI
from services.command_service import CommandService
from utils.helpers import setup_logger
from voice.voice_controller import VoiceController

logger = setup_logger("main")


class BotbroApp:
    def __init__(self):
        self._shutting_down = False
        self._original_excepthook = sys.excepthook
        self._signal_timer = None

        self.loop = asyncio.new_event_loop()
        self.async_thread = threading.Thread(
            target=self._run_async_loop,
            daemon=True,
            name="BotbroAsyncLoop",
        )
        self.async_thread.start()

        self.command_service = CommandService()
        self.voice_controller = VoiceController(command_service=self.command_service)

        self.app = QApplication(sys.argv)
        self.app.aboutToQuit.connect(self.shutdown)
        self._install_runtime_guards()

        self.gui = BotbroGUI(
            process_callback=self.process_text_input,
            voice_callback=self.process_voice_input,
        )

    def _run_async_loop(self):
        """Run the asyncio event loop in a background thread."""
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()

            if pending:
                try:
                    self.loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                except Exception as exc:
                    logger.debug(f"Async loop shutdown cleanup failed: {exc}")

            self.loop.close()

    def _safe_gui_emit(self, qt_signal, *args):
        if self._shutting_down:
            return False

        try:
            qt_signal.emit(*args)
            return True
        except RuntimeError as exc:
            logger.warning(f"Skipping GUI update during shutdown: {exc}")
            return False

    def _track_future(self, label: str, future: Future) -> None:
        def _done_callback(done_future: Future) -> None:
            try:
                done_future.result()
            except Exception as exc:
                logger.error(f"{label} task failed: {exc}")
                self._safe_gui_emit(
                    self.gui.signals.update_chat,
                    "System",
                    f"{label} task failed: {exc}",
                )
                self._safe_gui_emit(self.gui.signals.status_update, "Ready")

        future.add_done_callback(_done_callback)

    def _install_signal_handlers(self):
        """Close cleanly on POSIX consoles when Ctrl+C is pressed."""
        self._signal_timer = QTimer()
        self._signal_timer.timeout.connect(lambda: None)
        self._signal_timer.start(250)

        try:
            signal.signal(signal.SIGINT, self._handle_console_interrupt)
        except Exception as exc:
            logger.debug(f"SIGINT handler setup skipped: {exc}")

        if hasattr(signal, "SIGTERM"):
            try:
                signal.signal(signal.SIGTERM, self._handle_console_interrupt)
            except Exception as exc:
                logger.debug(f"SIGTERM handler setup skipped: {exc}")

    def _handle_console_interrupt(self, signum, _frame):
        logger.info(f"Received console signal {signum}; closing Botbro.")
        if not self._shutting_down:
            self.app.quit()

    def _install_runtime_guards(self):
        sys.excepthook = self._handle_uncaught_exception

        if os.name == "nt":
            self._ignore_windows_console_interrupts()
        else:
            self._install_signal_handlers()

    def _ignore_windows_console_interrupts(self):
        """Ignore Ctrl+C coming from an attached Windows console."""
        try:
            signal.signal(signal.SIGINT, signal.SIG_IGN)
        except Exception as exc:
            logger.debug(f"Windows SIGINT ignore setup skipped: {exc}")

        if hasattr(signal, "SIGBREAK"):
            try:
                signal.signal(signal.SIGBREAK, signal.SIG_IGN)
            except Exception as exc:
                logger.debug(f"Windows SIGBREAK ignore setup skipped: {exc}")

    def _handle_uncaught_exception(self, exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            logger.info("Ignored KeyboardInterrupt delivered to the GUI thread.")
            return

        self._original_excepthook(exc_type, exc_value, exc_traceback)

    def process_text_input(self, text: str):
        """Handle text input from the GUI."""
        if self._shutting_down or not self.loop.is_running():
            return

        logger.info(f"User text input: {text}")
        future = asyncio.run_coroutine_threadsafe(
            self._process_text_async(text),
            self.loop,
        )
        self._track_future("Text", future)

    async def _process_text_async(self, text: str):
        """Process text asynchronously and update the GUI safely."""
        response = await self.command_service.process_command(text)
        self._safe_gui_emit(self.gui.signals.update_chat, "Botbro", response)
        self._safe_gui_emit(self.gui.signals.status_update, "Ready")
        if not self._shutting_down:
            self.voice_controller.speak(response)

    def process_voice_input(self):
        """Handle voice input from the GUI."""
        if self._shutting_down or not self.loop.is_running():
            return

        def update_chat(sender, message):
            self._safe_gui_emit(self.gui.signals.update_chat, sender, message)

        def status_update(status):
            self._safe_gui_emit(self.gui.signals.status_update, status)

        future = asyncio.run_coroutine_threadsafe(
            self.voice_controller.process_voice_async(update_chat, status_update),
            self.loop,
        )
        self._track_future("Voice", future)

    def run(self):
        logger.info("Starting Botbro App...")
        self.gui.show()

        greeting = "Hello, I am Botbro. How can I assist you today?"
        self._safe_gui_emit(self.gui.signals.update_chat, "Botbro", greeting)
        self.voice_controller.speak(greeting)

        try:
            exit_code = self.app.exec_()
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received; shutting down cleanly.")
            self.app.quit()
            self.shutdown()
            exit_code = 0

        sys.exit(exit_code)

    def shutdown(self):
        if self._shutting_down:
            return

        self._shutting_down = True

        try:
            self.voice_controller.shutdown()
        except Exception as exc:
            logger.warning(f"Voice controller shutdown failed: {exc}")

        if self._signal_timer is not None:
            self._signal_timer.stop()

        sys.excepthook = self._original_excepthook

        if self.loop.is_running():
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except RuntimeError as exc:
                logger.debug(f"Async loop stop skipped: {exc}")

        if self.async_thread.is_alive():
            self.async_thread.join(timeout=2)


if __name__ == "__main__":
    assistant = BotbroApp()
    assistant.run()
