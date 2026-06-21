import sys
import os
import unittest
import asyncio
import time
import ast
import shutil
from unittest.mock import patch, MagicMock

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.ai_service import AIService
from core.executor import CommandExecutor
from config.settings import PENDING_CHANGE_TIMEOUT

class TestCodingAgent(unittest.TestCase):
    def setUp(self):
        self.workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Create a temp directory for file tests
        self.test_dir = os.path.join(self.workspace_dir, "tests", "temp_coding_test")
        os.makedirs(self.test_dir, exist_ok=True)

    def tearDown(self):
        # Clean up temp test directory files
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_workspace_tree_generation(self):
        tree = AIService._generate_workspace_tree(self.test_dir)
        self.assertTrue(tree.startswith("temp_coding_test/"))
        # Test that IGNORED_DIRS are skipped
        # Create an ignored directory and verify it is not in the tree
        ignored_path = os.path.join(self.test_dir, ".git")
        os.makedirs(ignored_path, exist_ok=True)
        tree_with_git = AIService._generate_workspace_tree(self.test_dir)
        self.assertNotIn(".git", tree_with_git)
        os.rmdir(ignored_path)

    def test_file_truncation_logic(self):
        # Test small file is NOT truncated
        small_file = os.path.join(self.test_dir, "small.py")
        content = "print('Hello')\n"
        with open(small_file, "w") as f:
            f.write(content)

        read_content = AIService._read_and_truncate_file(small_file)
        self.assertEqual(read_content, content)

        # Test large file is truncated
        large_file = os.path.join(self.test_dir, "large.py")
        large_content = "\n".join([f"line_{i}" for i in range(1000)])
        with open(large_file, "w") as f:
            f.write(large_content)

        read_large = AIService._read_and_truncate_file(large_file, max_size_bytes=2048)
        self.assertIn("[TRUNCATED", read_large)
        self.assertTrue(read_large.startswith("line_0"))
        self.assertTrue(read_large.strip().endswith("line_999"))

    def test_syntax_validation_staging(self):
        executor = CommandExecutor()
        py_file = os.path.join(self.test_dir, "code.py")
        with open(py_file, "w") as f:
            f.write("def func():\n    pass\n")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 1. Staging valid syntax
            intent_valid = {
                "intent": "modify_file",
                "target": py_file,
                "content": "def func():\n    print('valid syntax')\n"
            }
            res_valid = loop.run_until_complete(executor.execute_intent(intent_valid))
            self.assertIn("Proposed Changes for", res_valid)
            self.assertIsNotNone(executor.pending_change)

            # Clear change for next test
            executor.pending_change = None

            # 2. Staging invalid syntax
            intent_invalid = {
                "intent": "modify_file",
                "target": py_file,
                "content": "def func():\n    print('invalid syntax'\n" # Missing closing paren
            }
            res_invalid = loop.run_until_complete(executor.execute_intent(intent_invalid))
            self.assertIn("Syntax check failed", res_invalid)
            self.assertIsNone(executor.pending_change)
        finally:
            loop.close()

    def test_pending_change_confirmation_atomic_write_and_backup(self):
        executor = CommandExecutor()
        test_file = os.path.join(self.test_dir, "app.py")
        original_code = "def start():\n    print('starting')\n"
        with open(test_file, "w") as f:
            f.write(original_code)

        intent_modify = {
            "intent": "modify_file",
            "target": test_file,
            "content": "def start():\n    print('running')\n"
        }

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Stage the change
            loop.run_until_complete(executor.execute_intent(intent_modify))
            self.assertIsNotNone(executor.pending_change)

            # Confirm the change
            intent_confirm = {
                "intent": "chat_response",
                "target": "yes"
            }
            res_confirm = loop.run_until_complete(executor.execute_intent(intent_confirm))
            self.assertIn("Applied changes to", res_confirm)

            # Verify original file content was modified
            with open(test_file, "r") as f:
                updated_code = f.read()
            self.assertIn("print('running')", updated_code)

            # Verify backup file was created
            backup_file = test_file + ".botbro.bak"
            self.assertTrue(os.path.exists(backup_file))
            with open(backup_file, "r") as f:
                backup_code = f.read()
            self.assertEqual(backup_code, original_code)
        finally:
            loop.close()

    def test_pending_change_cancellation(self):
        executor = CommandExecutor()
        test_file = os.path.join(self.test_dir, "app.py")
        original_code = "def start():\n    print('starting')\n"
        with open(test_file, "w") as f:
            f.write(original_code)

        intent_modify = {
            "intent": "modify_file",
            "target": test_file,
            "content": "def start():\n    print('running')\n"
        }

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Stage the change
            loop.run_until_complete(executor.execute_intent(intent_modify))
            self.assertIsNotNone(executor.pending_change)

            # Cancel the change
            intent_cancel = {
                "intent": "chat_response",
                "target": "cancel"
            }
            res_cancel = loop.run_until_complete(executor.execute_intent(intent_cancel))
            self.assertIn("Staged changes discarded", res_cancel)
            self.assertIsNone(executor.pending_change)

            # Verify file remains unchanged
            with open(test_file, "r") as f:
                code = f.read()
            self.assertEqual(code, original_code)
        finally:
            loop.close()

    def test_show_pending_change(self):
        executor = CommandExecutor()
        test_file = os.path.join(self.test_dir, "app.py")
        with open(test_file, "w") as f:
            f.write("A = 1\n")

        intent_modify = {
            "intent": "modify_file",
            "target": test_file,
            "content": "A = 2\n"
        }

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Stage it
            loop.run_until_complete(executor.execute_intent(intent_modify))

            # Trigger show_pending_change
            intent_show = {
                "intent": "show_pending_change",
                "target": "pending"
            }
            res_show = loop.run_until_complete(executor.execute_intent(intent_show))
            self.assertIn("Current Staged Changes for", res_show)
            self.assertIn("-A = 1", res_show)
            self.assertIn("+A = 2", res_show)
        finally:
            loop.close()

    def test_change_timeout(self):
        executor = CommandExecutor()
        test_file = os.path.join(self.test_dir, "app.py")
        with open(test_file, "w") as f:
            f.write("A = 1\n")

        intent_modify = {
            "intent": "modify_file",
            "target": test_file,
            "content": "A = 2\n"
        }

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(executor.execute_intent(intent_modify))

            # Artificially set timestamp to 10 minutes ago
            executor.pending_change["created_at"] = time.time() - 600

            # Confirm changes - should expire
            intent_confirm = {
                "intent": "chat_response",
                "target": "apply"
            }
            res_confirm = loop.run_until_complete(executor.execute_intent(intent_confirm))
            self.assertIn("expired", res_confirm)
            self.assertIsNone(executor.pending_change)
        finally:
            loop.close()

    def test_prevent_concurrent_modifications(self):
        executor = CommandExecutor()
        test_file = os.path.join(self.test_dir, "app.py")
        with open(test_file, "w") as f:
            f.write("A = 1\n")

        intent_modify_1 = {
            "intent": "modify_file",
            "target": test_file,
            "content": "A = 2\n"
        }
        intent_modify_2 = {
            "intent": "modify_file",
            "target": test_file,
            "content": "A = 3\n"
        }

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Stage first change
            loop.run_until_complete(executor.execute_intent(intent_modify_1))
            self.assertIsNotNone(executor.pending_change)

            # Stage second change without confirming first - should block
            res_block = loop.run_until_complete(executor.execute_intent(intent_modify_2))
            self.assertIn("already have an active pending change", res_block)
            self.assertEqual(executor.pending_change["new_content"], "A = 2\n")
        finally:
            loop.close()

    def test_large_project_duplicate_filenames(self):
        # Create duplicate files
        src_dir = os.path.join(self.test_dir, "src")
        legacy_dir = os.path.join(self.test_dir, "legacy")
        os.makedirs(src_dir, exist_ok=True)
        os.makedirs(legacy_dir, exist_ok=True)

        src_main = os.path.join(src_dir, "main.py")
        legacy_main = os.path.join(legacy_dir, "main.py")

        with open(src_main, "w") as f:
            f.write("print('src')\n")
        with open(legacy_main, "w") as f:
            f.write("print('legacy')\n")

        executor = CommandExecutor()
        intent_modify = {
            "intent": "modify_file",
            "target": "main.py",
            "content": "print('updated')\n"
        }

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 1. Verify executor modify_file detects ambiguity
            res = loop.run_until_complete(executor.execute_intent(intent_modify))
            self.assertIn("Ambiguity Detected", res)
            self.assertIn("src/main.py", res)
            self.assertIn("legacy/main.py", res)
            self.assertIsNone(executor.pending_change)

            # Cleanup files inside test case to keep workspace clean
            os.remove(src_main)
            os.remove(legacy_main)
            os.rmdir(src_dir)
            os.rmdir(legacy_dir)
        finally:
            loop.close()

if __name__ == "__main__":
    unittest.main()
