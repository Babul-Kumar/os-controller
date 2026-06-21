import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.vector_memory import VectorMemory, MemoryEntry

class TestVectorMemory(unittest.TestCase):
    def setUp(self):
        # Use a temporary db file in the workspace
        self.db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_memory.db"))
        self.index_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_memory.faiss"))
        
        # Clean up any leftover test files
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        for path in (self.db_path, self.index_path):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    @patch("core.vector_memory._ST_AVAILABLE", True)
    @patch("core.vector_memory._FAISS_AVAILABLE", True)
    def test_remember_and_recall_with_faiss(self):
        # Mock the embedder and embed method to avoid downloading real model
        dummy_vector = np.random.randn(1, 384).astype(np.float32)
        
        with patch.object(VectorMemory, "embed", return_value=dummy_vector):
            vm = VectorMemory(db_path=self.db_path, index_path=self.index_path)
            
            # Remember some content
            entry_id = vm.remember("Test conversation memory", {"type": "conversation"})
            self.assertIsNotNone(entry_id)
            self.assertEqual(len(entry_id), 12)
            
            # Recall the content
            results = vm.recall("Test query")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].content, "Test conversation memory")
            self.assertEqual(results[0].metadata.get("type"), "conversation")
            self.assertTrue(results[0].similarity > 0 or results[0].similarity == 0)

    def test_learn_and_get_preferences(self):
        vm = VectorMemory(db_path=self.db_path, index_path=self.index_path)
        
        # Learn some preferences (uses keyword fallback if no embeddings mock is active)
        vm.learn_preference("preferred_editor_py", "vscode")
        vm.learn_preference("preferred_editor_txt", "notepad")
        
        prefs = vm.get_preferences()
        self.assertEqual(prefs.get("preferred_editor_py"), "vscode")
        self.assertEqual(prefs.get("preferred_editor_txt"), "notepad")

if __name__ == "__main__":
    unittest.main()
