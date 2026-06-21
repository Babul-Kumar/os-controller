import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.workflow_recorder import WorkflowRecorder, WorkflowEvent, _safe_name

class TestWorkflowRecorder(unittest.TestCase):
    def test_safe_name(self):
        self.assertEqual(_safe_name("My Super Workflow!!!"), "my_super_workflow")
        self.assertEqual(_safe_name("test-123"), "test-123")

    @patch("core.workflow_recorder._PYNPUT_AVAILABLE", True)
    @patch("core.workflow_recorder._mouse_lib")
    @patch("core.workflow_recorder._keyboard_lib")
    def test_start_stop_recording(self, mock_keyboard_lib, mock_mouse_lib):
        # Setup mocks
        mock_mouse_listener = MagicMock()
        mock_keyboard_listener = MagicMock()
        mock_mouse_lib.Listener.return_value = mock_mouse_listener
        mock_keyboard_lib.Listener.return_value = mock_keyboard_listener

        recorder = WorkflowRecorder()
        
        # Start
        msg = recorder.start_recording()
        self.assertEqual(msg, "Recording started. Perform your actions now.")
        self.assertTrue(recorder._recording)
        mock_mouse_listener.start.assert_called_once()
        mock_keyboard_listener.start.assert_called_once()
        
        # Stop
        stop_msg = recorder.stop_recording()
        self.assertIn("Recording stopped", stop_msg)
        self.assertFalse(recorder._recording)
        mock_mouse_listener.stop.assert_called_once()
        mock_keyboard_listener.stop.assert_called_once()

    def test_filter_mouse_moves(self):
        events = [
            WorkflowEvent(event_type="mouse_move", x=100, y=100),
            WorkflowEvent(event_type="mouse_move", x=110, y=110), # dist ~14px (filtered)
            WorkflowEvent(event_type="mouse_move", x=160, y=160), # dist ~70px (kept)
            WorkflowEvent(event_type="mouse_click", x=160, y=160, button="left") # kept (click)
        ]
        
        filtered = WorkflowRecorder._filter_mouse_moves(events)
        self.assertEqual(len(filtered), 3)
        self.assertEqual(filtered[0].x, 100)
        self.assertEqual(filtered[1].x, 160)
        self.assertEqual(filtered[2].event_type, "mouse_click")

if __name__ == "__main__":
    unittest.main()
