import sys
import os
import unittest
import asyncio
import time
import shutil
import json

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.code_intelligence.cache_manager import CacheManager
from core.code_intelligence.ast_indexer import ASTIndexer
from core.code_intelligence.dependency_resolver import DependencyResolver
from core.code_intelligence.call_graph import CallGraphExtractor
from core.code_intelligence.search_engine import SearchEngine
from core.executor import CommandExecutor


class TestCodeIntelligence(unittest.TestCase):
    def setUp(self):
        self.workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.test_dir = os.path.join(self.workspace_dir, "tests", "temp_code_intel_test")
        os.makedirs(self.test_dir, exist_ok=True)
        self.cache_manager = CacheManager(self.test_dir)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_circular_and_relative_imports(self):
        # Create circular imports: a.py imports b.py; b.py imports a.py
        # Also create nested relative import: nested/c.py imports ..a
        nested_dir = os.path.join(self.test_dir, "nested")
        os.makedirs(nested_dir, exist_ok=True)

        with open(os.path.join(self.test_dir, "a.py"), "w", encoding="utf-8") as f:
            f.write("import b\nclass A:\n    pass\n")

        with open(os.path.join(self.test_dir, "b.py"), "w", encoding="utf-8") as f:
            f.write("import a\ndef func_b():\n    pass\n")

        with open(os.path.join(nested_dir, "c.py"), "w", encoding="utf-8") as f:
            f.write("from .. import a\n")

        # Rebuild/load index
        self.cache_manager.load_or_rebuild_index(ignored_dirs=set())

        # Check forward and reverse dependencies
        deps = self.cache_manager.dependency_graph
        self.assertIn("a.py", deps["forward"])
        self.assertIn("b.py", deps["forward"]["a.py"])
        self.assertIn("b.py", deps["forward"])
        self.assertIn("a.py", deps["forward"]["b.py"])

        # Check reverse dependencies
        self.assertIn("a.py", deps["reverse"])
        self.assertIn("b.py", deps["reverse"]["a.py"])
        self.assertIn("b.py", deps["reverse"])
        self.assertIn("a.py", deps["reverse"]["b.py"])

        # Test circular protection in transitive dependencies
        trans_a = DependencyResolver.get_transitive_context(deps["forward"], "a.py")
        self.assertIn("b.py", trans_a)
        # Should not infinite loop and should return sorted list
        self.assertEqual(len(trans_a), 1)

    def test_duplicate_symbols_handling(self):
        # Create two files with a class of the same name but different methods
        with open(os.path.join(self.test_dir, "logger_one.py"), "w", encoding="utf-8") as f:
            f.write("class Logger:\n    def log_one(self):\n        pass\n")

        with open(os.path.join(self.test_dir, "logger_two.py"), "w", encoding="utf-8") as f:
            f.write("class Logger:\n    def log_two(self):\n        pass\n")

        self.cache_manager.load_or_rebuild_index(ignored_dirs=set())

        # Look up Logger
        results = SearchEngine.symbol_lookup(self.cache_manager.code_index, "Logger")
        # Should return both matching classes
        self.assertEqual(len(results), 2)
        symbol_ids = [r["id"] for r in results]
        self.assertIn("logger_one.py::Logger", symbol_ids)
        self.assertIn("logger_two.py::Logger", symbol_ids)

    def test_cache_corruption_recovery(self):
        # Setup files and initial index
        with open(os.path.join(self.test_dir, "main.py"), "w", encoding="utf-8") as f:
            f.write("def start():\n    pass\n")

        self.cache_manager.load_or_rebuild_index(ignored_dirs=set())
        self.assertTrue(os.path.exists(self.cache_manager.code_index_file))

        # Corrupt code_index.json by writing invalid JSON
        with open(self.cache_manager.code_index_file, "w", encoding="utf-8") as f:
            f.write("{invalid_json:")

        # Re-run indexer. It should detect corruption, clear cache, and rebuild
        self.cache_manager.load_or_rebuild_index(ignored_dirs=set())
        self.assertIn("main.py::start", self.cache_manager.code_index)

    def test_incremental_updates_and_file_ownership(self):
        # 1. Initial build
        with open(os.path.join(self.test_dir, "main.py"), "w", encoding="utf-8") as f:
            f.write("def main_func():\n    pass\n")

        self.cache_manager.load_or_rebuild_index(ignored_dirs=set())
        self.assertIn("main.py::main_func", self.cache_manager.code_index)
        
        # Verify File Ownership Metadata is stored in cache_metadata.json
        metadata = self.cache_manager.load_json_file(self.cache_manager.metadata_file)
        self.assertIn("main.py", metadata["files"])
        self.assertIn("main.py::main_func", metadata["files"]["main.py"]["symbols"])

        # 2. Modify file to add a new symbol and remove old symbol
        time.sleep(0.1) # Ensure mtime changes
        with open(os.path.join(self.test_dir, "main.py"), "w", encoding="utf-8") as f:
            f.write("def new_main():\n    pass\n")

        self.cache_manager.load_or_rebuild_index(ignored_dirs=set())
        # Old symbol should be removed, new symbol should exist
        self.assertNotIn("main.py::main_func", self.cache_manager.code_index)
        self.assertIn("main.py::new_main", self.cache_manager.code_index)

        # 3. Add a new file and reference new_main
        with open(os.path.join(self.test_dir, "caller.py"), "w", encoding="utf-8") as f:
            f.write("import main\nmain.new_main()\n")

        self.cache_manager.load_or_rebuild_index(ignored_dirs=set())
        self.assertIn("main.py::new_main", self.cache_manager.reference_index)
        caller_refs = self.cache_manager.reference_index["main.py::new_main"]
        self.assertTrue(any(r["file_path"] == "caller.py" for r in caller_refs))

        # 4. Delete caller.py and check incremental cleanup
        os.remove(os.path.join(self.test_dir, "caller.py"))
        self.cache_manager.load_or_rebuild_index(ignored_dirs=set())
        # Reference should be cleared
        self.assertNotIn("main.py::new_main", self.cache_manager.reference_index)

    def test_performance_targets(self):
        # Create a medium sized project structure (20 files)
        for i in range(20):
            with open(os.path.join(self.test_dir, f"module_{i}.py"), "w", encoding="utf-8") as f:
                f.write(f"class Class_{i}:\n    def method_{i}(self):\n        pass\n\ndef helper_{i}():\n    pass\n")

        # Initial index build target: <5s (usually <200ms for 20 files)
        t_start = time.perf_counter()
        self.cache_manager.load_or_rebuild_index(ignored_dirs=set())
        t_build = time.perf_counter() - t_start
        self.assertLess(t_build, 5.0)

        # Incremental rebuild target with no changes: <0.2s (valid cache)
        t_start = time.perf_counter()
        self.cache_manager.load_or_rebuild_index(ignored_dirs=set())
        t_startup_valid = time.perf_counter() - t_start
        self.assertLess(t_startup_valid, 0.2)

        # Reindexing target with 1 modified file: <0.5s
        time.sleep(0.1)
        with open(os.path.join(self.test_dir, "module_0.py"), "w", encoding="utf-8") as f:
            f.write("class Class_0:\n    def modified_method(self):\n        pass\n")
        
        t_start = time.perf_counter()
        self.cache_manager.load_or_rebuild_index(ignored_dirs=set())
        t_rebuild = time.perf_counter() - t_start
        self.assertLess(t_rebuild, 0.5)

    def test_executor_intents(self):
        # Create code files to query via intents
        with open(os.path.join(self.test_dir, "voice.py"), "w", encoding="utf-8") as f:
            f.write("class VoiceController:\n    def start_listening(self):\n        \"\"\"Starts listening to voice.\"\"\"\n        print('listening')\n")

        with open(os.path.join(self.test_dir, "main.py"), "w", encoding="utf-8") as f:
            f.write("from voice import VoiceController\nvc = VoiceController()\nvc.start_listening()\n")

        # Build index first
        self.cache_manager.load_or_rebuild_index(ignored_dirs=set())

        # Instantiate executor using our test cache_manager
        executor = CommandExecutor(self.cache_manager)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 1. find_symbol
            res_symbol = loop.run_until_complete(executor.execute_intent({
                "intent": "find_symbol",
                "target": "VoiceController"
            }))
            self.assertIn("Found 1 symbols", res_symbol)
            self.assertIn("voice.py", res_symbol)
            self.assertIn("class VoiceController", res_symbol)

            # 2. find_references
            res_refs = loop.run_until_complete(executor.execute_intent({
                "intent": "find_references",
                "target": "VoiceController"
            }))
            self.assertIn("Found 1 references", res_refs)
            self.assertIn("main.py", res_refs)

            # 3. trace_execution
            res_trace = loop.run_until_complete(executor.execute_intent({
                "intent": "trace_execution",
                "target": "VoiceController.start_listening"
            }))
            self.assertIn("Execution Trace for", res_trace)
            self.assertIn("VoiceController.start_listening", res_trace)

            # 4. list_symbols
            res_list = loop.run_until_complete(executor.execute_intent({
                "intent": "list_symbols",
                "target": "voice.py"
            }))
            self.assertIn("Symbols defined in", res_list)
            self.assertIn("VoiceController", res_list)
        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main()
