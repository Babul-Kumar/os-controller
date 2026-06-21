import sys
import os
import unittest
import asyncio
from unittest.mock import patch, MagicMock

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.executor import CommandExecutor

class TestScreenUnderstanding(unittest.TestCase):
    @patch("automation.screen_reader.ScreenReader.take_screenshot")
    @patch("automation.screen_reader.ScreenReader.read_full_screen_text")
    @patch("services.ollama_service.call_ollama")
    def test_screen_info_analysis_success(self, mock_call_ollama, mock_read_text, mock_take_screenshot):
        # Setup mocks
        mock_take_screenshot.return_value = "mock_screenshots/latest_screen.png"
        mock_read_text.return_value = "Traceback (most recent call last):\n  File \"app.py\", line 12, in <module>\n    import winreg\nModuleNotFoundError: No module named 'winreg'"
        mock_call_ollama.return_value = "This error occurs because the 'winreg' module is Windows-only. To fix it, wrap it in a try-except block."

        executor = CommandExecutor()
        intent_data = {
            "intent": "screen_info",
            "target": "error",
            "content": "what is this error?"
        }

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(executor.execute_intent(intent_data))
            self.assertIn("Screen text analyzed.", result)
            self.assertEqual(mock_read_text.call_count, 1)
            self.assertIn("This error occurs because the 'winreg' module is Windows-only.", result)
            mock_call_ollama.assert_called_once()
        finally:
            loop.close()

    @patch("automation.screen_reader.ScreenReader.take_screenshot")
    @patch("automation.screen_reader.ScreenReader.read_full_screen_text")
    @patch("automation.screen_reader.ScreenReader.describe_screen")
    def test_screen_info_fallback_on_empty_text(self, mock_describe_screen, mock_read_text, mock_take_screenshot):
        # Setup mocks to return empty OCR text
        mock_take_screenshot.return_value = "mock_screenshots/latest_screen.png"
        mock_read_text.return_value = "   \n  "
        mock_describe_screen.return_value = {
            "resolution": "1920x1080",
            "brightness": 120,
            "mode": "dark"
        }

        executor = CommandExecutor()
        intent_data = {
            "intent": "screen_info",
            "target": "screen"
        }

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(executor.execute_intent(intent_data))
            self.assertIn("No readable text was found on the screen", result)
            self.assertIn("1920x1080", result)
            self.assertIn("dark mode", result)
        finally:
            loop.close()

if __name__ == "__main__":
    unittest.main()
