import sys
import os
import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.orchestrator import AgentOrchestrator
from core.agents.base_agent import AgentTask, AgentResult

class TestOrchestrator(unittest.TestCase):
    def test_is_complex_task(self):
        self.assertTrue(AgentOrchestrator.is_complex_task("create a flask application"))
        self.assertTrue(AgentOrchestrator.is_complex_task("build me a portfolio website"))
        self.assertFalse(AgentOrchestrator.is_complex_task("open notepad"))
        self.assertFalse(AgentOrchestrator.is_complex_task("search for python tutorials"))

    @patch("core.orchestrator.PlannerAgent")
    @patch("core.orchestrator.CoderAgent")
    @patch("core.orchestrator.ExecutorAgent")
    @patch("core.orchestrator.VerifierAgent")
    def test_run_complex_task_success(self, mock_verifier_cls, mock_executor_cls, mock_coder_cls, mock_planner_cls):
        # Instantiate mock agents
        mock_planner = mock_planner_cls.return_value
        mock_coder = mock_coder_cls.return_value
        mock_executor = mock_executor_cls.return_value
        mock_verifier = mock_verifier_cls.return_value
        
        # Configure mock names
        mock_planner.name = "Planner"
        mock_coder.name = "Coder"
        mock_executor.name = "Executor"
        mock_verifier.name = "Verifier"
        
        # Configure Planner mock output: returns a single step task
        step_task = AgentTask(goal="Create main.py", context={"intent": "create_file", "target": "main.py"})
        mock_planner.run = AsyncMock(return_value=AgentResult(success=True, output="Planned steps", next_tasks=[step_task]))
        
        # Configure Coder mock output
        mock_coder.run = AsyncMock(return_value=AgentResult(success=True, output="Coded", artifacts={"code": "print('hello')"}))
        
        # Configure Executor mock output
        mock_executor.run = AsyncMock(return_value=AgentResult(success=True, output="File created successfully"))
        
        # Configure Verifier mock output
        mock_verifier.run = AsyncMock(return_value=AgentResult(success=True, output="Verified successfully"))
        
        orchestrator = AgentOrchestrator()
        
        # Run orchestrator
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                orchestrator.run_complex_task("build a small test app")
            )
            
            # Assertions
            self.assertIn("Task completed", result)
            self.assertIn("Create main.py", result)
            self.assertIn("File created successfully", result)
            
            # Check calls
            mock_planner.run.assert_called_once()
            mock_coder.run.assert_called_once()
            mock_executor.run.assert_called_once()
            mock_verifier.run.assert_called_once()
        finally:
            loop.close()

if __name__ == "__main__":
    unittest.main()
