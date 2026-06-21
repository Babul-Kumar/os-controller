import re
import os
import math
from typing import Dict, List, Any, Optional, Tuple

class SearchEngine:
    @staticmethod
    def symbol_lookup(code_index: Dict[str, Any], query: str) -> List[Dict[str, Any]]:
        """Find definitions of symbols matching the query (exact or partial).
        
        Matches unique symbol IDs (e.g. "file.py::ClassName") or simple names.
        """
        results = []
        query_clean = query.strip().lower()
        
        # 1. Exact match (case insensitive) on symbol name
        for symbol_id, info in code_index.items():
            if info.get("name", "").lower() == query_clean:
                results.append({"id": symbol_id, "score": 1.0, **info})
                
        # 2. Match parent class methods: ClassName.method_name
        if "." in query:
            parts = query.split(".")
            class_part = parts[0].lower()
            method_part = parts[1].lower()
            for symbol_id, info in code_index.items():
                parent = (info.get("parent") or "").lower()
                name = info.get("name", "").lower()
                if parent == class_part and name == method_part:
                    results.append({"id": symbol_id, "score": 0.95, **info})
                    
        # 3. Partial match as fallback if no exact matches found
        if not results:
            for symbol_id, info in code_index.items():
                if query_clean in info.get("name", "").lower() or query_clean in symbol_id.lower():
                    results.append({"id": symbol_id, "score": 0.5, **info})
                    
        # Sort by score desc
        return sorted(results, key=lambda x: x["score"], reverse=True)

    @staticmethod
    def reference_lookup(reference_index: Dict[str, Any], symbol_id: str) -> List[Dict[str, Any]]:
        """Look up all recorded occurrences of a symbol ID inside the reference index."""
        # Find exact matches
        refs = reference_index.get(symbol_id, [])
        
        # If not found directly, check if the symbol_id matches a suffix or partial symbol
        if not refs:
            for ref_id, occurrences in reference_index.items():
                if ref_id.endswith(f"::{symbol_id}") or ref_id.endswith(f"::{symbol_id}"):
                    return occurrences
        return refs

    @staticmethod
    def keyword_search(code_index: Dict[str, Any], keyword: str) -> List[Dict[str, Any]]:
        """Search symbol docstrings and snippets for keyword occurrences."""
        results = []
        kw_lower = keyword.strip().lower()
        if not kw_lower:
            return results
            
        for symbol_id, info in code_index.items():
            doc = info.get("docstring", "").lower()
            name = info.get("name", "").lower()
            snippet = info.get("snippet", "").lower()
            
            score = 0.0
            if kw_lower in name:
                score += 0.8
            if kw_lower in doc:
                score += 0.4
            if kw_lower in snippet:
                score += 0.1
                
            if score > 0.0:
                results.append({"id": symbol_id, "score": score, **info})
                
        return sorted(results, key=lambda x: x["score"], reverse=True)

    @staticmethod
    def tf_idf_search(workspace_dir: str, files: List[str], query: str) -> List[Tuple[str, float]]:
        """Run a lightweight TF-IDF text search fallback over the actual contents of files."""
        # 1. Clean query into words
        query_words = re.findall(r"\b\w{3,}\b", query.lower())
        if not query_words:
            return []
            
        # 2. Build term frequencies (TF) per file and document frequency (DF)
        doc_tfs: Dict[str, Dict[str, int]] = {}
        doc_lens: Dict[str, int] = {}
        dfs: Dict[str, int] = {}
        
        valid_files = []
        for rel_path in files:
            full_path = os.path.join(workspace_dir, rel_path)
            if not os.path.isfile(full_path):
                continue
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().lower()
                words = re.findall(r"\b\w{3,}\b", content)
                if not words:
                    continue
                    
                valid_files.append(rel_path)
                doc_lens[rel_path] = len(words)
                
                # TF counts
                tf = {}
                for w in words:
                    tf[w] = tf.get(w, 0) + 1
                doc_tfs[rel_path] = tf
                
                # Update DF counts for words appearing in query
                for w in set(tf.keys()):
                    if w in query_words:
                        dfs[w] = dfs.get(w, 0) + 1
            except Exception:
                continue
                
        # 3. Compute TF-IDF scores
        N = len(valid_files)
        scores: List[Tuple[str, float]] = []
        
        for rel_path in valid_files:
            score = 0.0
            tf_map = doc_tfs[rel_path]
            length = doc_lens[rel_path]
            
            for w in query_words:
                tf_count = tf_map.get(w, 0)
                if tf_count > 0:
                    tf_score = tf_count / length
                    df_count = dfs.get(w, 0)
                    idf_score = math.log((N + 1) / (df_count + 1)) + 1
                    score += tf_score * idf_score
                    
            if score > 0.0:
                scores.append((rel_path, score))
                
        return sorted(scores, key=lambda x: x[1], reverse=True)
