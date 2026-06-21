import sys
import os
import unittest
import asyncio
from unittest.mock import MagicMock, patch

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from automation.feedback_loop import FeedbackLoop, VerificationResult

class TestFeedbackLoop(unittest.TestCase):
    @patch("automation.feedback_loop.gw")
    @patch("automation.feedback_loop.pyautogui")
    def test_verify_app_opened_success(self, mock_pyautogui, mock_gw):
        mock_gw.getAllTitles.return_value = ["Calculator", "Notepad", "Chrome"]
        fl = FeedbackLoop()
        
        # Mock take_verification_screenshot to not do actual screenshot saving
        fl.take_verification_screenshot = MagicMock(return_value="mock_path.png")
        
        result = fl.verify_app_opened("notepad", timeout=1)
        self.assertTrue(result.success)
        self.assertEqual(result.screenshot_path, "mock_path.png")
        self.assertIn("Notepad", result.detected_windows)

    @patch("automation.feedback_loop.gw")
    def test_verify_app_opened_timeout(self, mock_gw):
        mock_gw.getAllTitles.return_value = ["Calculator", "Chrome"]
        fl = FeedbackLoop()
        
        result = fl.verify_app_opened("notepad", timeout=1)
        self.assertFalse(result.success)
        self.assertNotIn("Notepad", result.detected_windows)

    @patch("automation.feedback_loop.gw")
    def test_verify_window_has_content(self, mock_gw):
        mock_gw.getAllTitles.return_value = ["Notepad"]
        mock_win = MagicMock()
        mock_win.width = 800
        mock_win.height = 600
        mock_gw.getWindowsWithTitle.return_value = [mock_win]
        
        fl = FeedbackLoop()
        result = fl.verify_window_has_content("notepad")
        self.assertTrue(result.success)
        self.assertIn("has content", result.message)

    @patch("automation.feedback_loop._OCR_AVAILABLE", False)
    @patch("automation.feedback_loop.gw")
    def test_verify_text_on_screen_fallback(self, mock_gw):
        # When OCR is not available, check window title matching
        mock_gw.getAllTitles.return_value = ["My Unique Title"]
        fl = FeedbackLoop()
        
        result = fl.verify_text_on_screen("Unique Title", timeout=1)
        self.assertTrue(result.success)
        self.assertIn("fallback", result.message.lower())

    def test_retry_with_feedback_success(self):
        fl = FeedbackLoop()
        
        # Mock action coroutine
        async def mock_action():
            return "done"
            
        action_coro = mock_action()
        
        # Mock verify_fn that passes on first attempt
        verify_fn = MagicMock(return_value=VerificationResult(success=True, message="Looks good"))
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            success, result = loop.run_until_complete(
                fl.retry_with_feedback(action_coro, verify_fn, max_retries=2, delay=0.1)
            )
            self.assertTrue(success)
            self.assertTrue(result.success)
            self.assertEqual(verify_fn.call_count, 1)
        finally:
            loop.close()

if __name__ == "__main__":
    unittest.main()
