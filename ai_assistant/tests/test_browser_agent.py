import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from automation.browser_agent import BrowserAgent, BrowserStep, BrowserResult

class TestBrowserAgent(unittest.TestCase):
    @patch("automation.browser_agent._SELENIUM_AVAILABLE", True)
    @patch("automation.browser_agent._WDM_AVAILABLE", False)
    @patch("automation.browser_agent.webdriver")
    def test_init_driver(self, mock_webdriver):
        mock_driver = MagicMock()
        mock_webdriver.Chrome.return_value = mock_driver
        
        agent = BrowserAgent()
        agent._init_driver()
        
        self.assertIsNotNone(agent.driver)
        mock_webdriver.Chrome.assert_called_once()
        agent.close()
        mock_driver.quit.assert_called_once()

    @patch("automation.browser_agent._SELENIUM_AVAILABLE", True)
    @patch("services.ollama_service.call_ollama")
    def test_plan_steps_ollama_success(self, mock_call_ollama):
        mock_call_ollama.return_value = """
        [
            {"action": "navigate", "value": "https://github.com", "description": "Go to GitHub"}
        ]
        """
        agent = BrowserAgent()
        steps = agent.plan_steps("Go to Github")
        
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].action, "navigate")
        self.assertEqual(steps[0].value, "https://github.com")
        self.assertEqual(steps[0].description, "Go to GitHub")

    def test_fallback_plan(self):
        agent = BrowserAgent()
        steps = agent._fallback_plan("Test goal")
        
        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0].action, "navigate")
        self.assertEqual(steps[0].value, "https://www.google.com")
        self.assertEqual(steps[1].action, "type_into")
        self.assertEqual(steps[1].value, "Test goal")

    @patch("automation.browser_agent._SELENIUM_AVAILABLE", True)
    def test_execute_steps_success(self):
        agent = BrowserAgent()
        # Mock driver
        mock_driver = MagicMock()
        agent.driver = mock_driver
        
        # Mock take screenshot
        agent._take_screenshot = MagicMock(return_value="shot.png")
        
        steps = [
            BrowserStep(action="navigate", value="https://example.com"),
            BrowserStep(action="scroll_down")
        ]
        
        # Mock dispatch step
        agent._dispatch_step = MagicMock(return_value=None)
        
        result = agent.execute_steps(steps)
        self.assertTrue(result.success)
        self.assertEqual(result.steps_completed, 2)
        self.assertEqual(len(result.screenshots), 1)  # only navigate takes screenshot in default mock list

if __name__ == "__main__":
    unittest.main()
