import sys
import os
import asyncio
import unittest

# Ensure the parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.command_parser import CommandParser
from core.security import validate_shell_command
from services.command_service import CommandService

class TestBotbroCore(unittest.TestCase):
    def test_command_parser_clean(self):
        raw_response = '```json\n{"intent": "open_app", "target": "chrome"}\n```'
        parsed = CommandParser.parse(raw_response)
        self.assertEqual(parsed.get("intent"), "open_app")
        self.assertEqual(parsed.get("target"), "chrome")

    def test_command_parser_malformed(self):
        raw_response = 'Here is the response: {"action": "web_search", "query": "python programming"}'
        parsed = CommandParser.parse(raw_response)
        self.assertEqual(parsed.get("intent"), "web_search")
        self.assertEqual(parsed.get("target"), "python programming")

    def test_security_layer(self):
        safe, reason = validate_shell_command("notepad.exe")
        self.assertTrue(safe)

        safe, reason = validate_shell_command("notepad.exe & rm -rf /")
        self.assertFalse(safe)
        
        safe, reason = validate_shell_command("calc.exe | shutdown /s")
        self.assertFalse(safe)
        
        safe, reason = validate_shell_command("echo `whoami`")
        self.assertFalse(safe)

    def test_command_service_initialization(self):
        service = CommandService()
        self.assertIsNotNone(service.plugin_manager)
        self.assertIsNotNone(service.ai_service)
        self.assertIsNotNone(service.executor)

    def test_async_command_processing(self):
        service = CommandService()
        
        async def mock_execute(intent_data):
            return f"Mocked execution of {intent_data.get('intent')} on {intent_data.get('target')}"
            
        service.executor.execute_intent = mock_execute
        
        async def run_test():
            # Test a basic fallback command so we don't rely entirely on Ollama responding fast
            res = await service.process_command("open calculator")
            return res
            
        # Instead of asyncio.run which can conflict with existing loops in tests, use the standard pattern
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            res = loop.run_until_complete(run_test())
            self.assertTrue(isinstance(res, str))
            self.assertIn("Mocked execution", res)
        finally:
            loop.close()

if __name__ == '__main__':
    unittest.main()
