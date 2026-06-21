import os
import json
import hashlib
import time
import logging
from typing import Dict, Any, List, Set, Tuple

logger = logging.getLogger(__name__)

CACHE_DIR_NAME = ".botbro"
SCHEMA_VERSION = 2

class CacheManager:
    def __init__(self, workspace_dir: str):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.cache_dir = os.path.join(self.workspace_dir, CACHE_DIR_NAME)
        
        # Files under .botbro/
        self.metadata_file = os.path.join(self.cache_dir, "cache_metadata.json")
        self.code_index_file = os.path.join(self.cache_dir, "code_index.json")
        self.dependency_graph_file = os.path.join(self.cache_dir, "dependency_graph.json")
        self.file_summaries_file = os.path.join(self.cache_dir, "file_summaries.json")
        self.reference_index_file = os.path.join(self.cache_dir, "reference_index.json")

        self.code_index = {}
        self.dependency_graph = {"forward": {}, "reverse": {}}
        self.file_summaries = {}
        self.reference_index = {}

    def _ensure_cache_dir(self):
        os.makedirs(self.cache_dir, exist_ok=True)

    def clear_cache(self):
        """Delete all cached index files to force a clean rebuild."""
        logger.info("Clearing Botbro codebase intelligence cache...")
        for file_path in [self.metadata_file, self.code_index_file, self.dependency_graph_file, 
                          self.file_summaries_file, self.reference_index_file]:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    logger.warning(f"Failed to remove cache file {file_path}: {e}")

    def load_json_file(self, file_path: str) -> Dict[str, Any]:
        """Load JSON file. Triggers cache corruption recovery if the JSON is malformed."""
        if not os.path.exists(file_path):
            return {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.error(f"Cache corruption detected in {file_path}: {e}. Triggering full rebuild.")
            self.clear_cache()
            return {}

    def save_json_file(self, file_path: str, data: Any):
        self._ensure_cache_dir()
        # Atomic write to avoid corruption during mid-write crash
        dir_name = os.path.dirname(file_path)
        base_name = os.path.basename(file_path)
        
        # Create temp file in same directory
        temp_fd = None
        temp_path = None
        try:
            import tempfile
            with tempfile.NamedTemporaryFile("w", dir=dir_name, prefix=f".tmp_{base_name}", delete=False, encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
                temp_path = f.name
            os.replace(temp_path, file_path)
        except Exception as e:
            logger.error(f"Failed to write cache file atomically {file_path}: {e}")
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    def compute_file_hash(self, file_path: str) -> str:
        """Compute MD5 hash of file content."""
        hasher = hashlib.md5()
        try:
            with open(file_path, 'rb') as f:
                buf = f.read(65536)
                while len(buf) > 0:
                    hasher.update(buf)
                    buf = f.read(65536)
            return hasher.hexdigest()
        except Exception as e:
            logger.warning(f"Could not compute hash for {file_path}: {e}")
            return ""

    def scan_workspace(self, ignored_dirs: Set[str]) -> Tuple[List[str], List[str], Dict[str, Dict[str, Any]]]:
        """Scan workspace to identify added, modified, and deleted python/code files.
        
        Returns:
            to_reindex: List of file paths to parse
            to_delete: List of relative paths that were deleted
            new_metadata: Updated file metadata dict
        """
        # Load existing metadata
        metadata = self.load_json_file(self.metadata_file)
        
        # Verify schema version
        if metadata.get("schema_version") != SCHEMA_VERSION:
            logger.info(f"Schema version mismatch ({metadata.get('schema_version')} != {SCHEMA_VERSION}). Forcing clean index.")
            self.clear_cache()
            metadata = {}

        old_files = metadata.get("files", {})
        new_files = {}
        to_reindex = []
        
        # Walk workspace to find files
        for root, dirs, files in os.walk(self.workspace_dir):
            dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith(".")]
            for file in files:
                if file.endswith((".py", ".txt", ".js", ".ts", ".html", ".css", ".java", ".cpp", ".c", ".json", ".csv", ".md")):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, self.workspace_dir).replace("\\", "/")
                    
                    # Track last modified and hash
                    mtime = os.path.getmtime(full_path)
                    new_files[rel_path] = {
                        "last_modified": mtime,
                        "hash": "", # Computed below if modified
                        "symbols": []
                    }

        # Find deleted files
        to_delete = []
        for rel_path in old_files:
            if rel_path not in new_files:
                to_delete.append(rel_path)
                logger.info(f"Detected deleted file: {rel_path}")

        # Find added or modified files
        for rel_path, file_info in new_files.items():
            old_info = old_files.get(rel_path)
            if not old_info:
                # File is new
                file_info["hash"] = self.compute_file_hash(os.path.join(self.workspace_dir, rel_path))
                to_reindex.append(rel_path)
                logger.info(f"Detected new file: {rel_path}")
            elif file_info["last_modified"] != old_info.get("last_modified"):
                # Timestamp changed, verify with hash
                curr_hash = self.compute_file_hash(os.path.join(self.workspace_dir, rel_path))
                file_info["hash"] = curr_hash
                if curr_hash != old_info.get("hash"):
                    to_reindex.append(rel_path)
                    logger.info(f"Detected modified file: {rel_path}")
                else:
                    # Timestamp changed but hash matches, update timestamp only and copy symbols
                    file_info["symbols"] = old_info.get("symbols", [])
            else:
                # Unmodified file
                file_info["hash"] = old_info.get("hash")
                file_info["symbols"] = old_info.get("symbols", [])

        # Create updated metadata structure
        updated_metadata = {
            "schema_version": SCHEMA_VERSION,
            "created_at": metadata.get("created_at", time.time()),
            "updated_at": time.time(),
            "workspace_hash": hashlib.md5(self.workspace_dir.encode("utf-8")).hexdigest(),
            "files": new_files
        }

        return to_reindex, to_delete, updated_metadata

    def load_or_rebuild_index(self, ignored_dirs: Set[str] = None):
        """Startup scan to load or incrementally update/rebuild the codebase index."""
        if ignored_dirs is None:
            from config.settings import IGNORED_DIRS
            ignored_dirs = IGNORED_DIRS

        to_reindex, to_delete, updated_metadata = self.scan_workspace(ignored_dirs)

        self.code_index = self.load_json_file(self.code_index_file)
        self.dependency_graph = self.load_json_file(self.dependency_graph_file)
        self.file_summaries = self.load_json_file(self.file_summaries_file)
        self.reference_index = self.load_json_file(self.reference_index_file)

        if not self.code_index:
            logger.info("Code index is empty/corrupt. Performing full workspace index build.")
            to_reindex = list(updated_metadata["files"].keys())
            to_delete = []
            self.code_index = {}
            self.dependency_graph = {"forward": {}, "reverse": {}}
            self.file_summaries = {}
            self.reference_index = {}

        if to_reindex or to_delete:
            logger.info(f"Index out of date. Reindexing {len(to_reindex)} files, deleting {len(to_delete)} files.")
            self._update_index(to_reindex, to_delete, updated_metadata)
        else:
            logger.info("Code intelligence index is up to date.")

    def _update_index(self, to_reindex: List[str], to_delete: List[str], updated_metadata: Dict[str, Any]):
        """Incrementally update indices for deleted and modified/new files."""
        # 1. Process deleted files
        for rel_path in to_delete:
            # We can immediately purge symbols owned by this file using File Ownership Metadata!
            # Old metadata files list contains symbols list if we had them loaded.
            # But to be safe, we can check code_index.
            symbols_to_remove = [sym_id for sym_id in self.code_index if sym_id.startswith(f"{rel_path}::")]
            for sym_id in symbols_to_remove:
                self.code_index.pop(sym_id, None)
                self.reference_index.pop(sym_id, None)

            self.file_summaries.pop(rel_path, None)

            # Filter references from this file
            for sym_id in list(self.reference_index.keys()):
                self.reference_index[sym_id] = [ref for ref in self.reference_index[sym_id] if ref.get("file_path") != rel_path]
                if not self.reference_index[sym_id]:
                    self.reference_index.pop(sym_id, None)

        # 2. Process reindexed files
        from core.code_intelligence.ast_indexer import ASTIndexer
        for rel_path in to_reindex:
            # Remove old symbols for this file using cache_metadata first if possible, or prefix matching
            # Let's check existing cache_metadata for symbols owned by this file (before updating)
            # If we load metadata, we can see the old file entry.
            # But prefix matching is also extremely safe and fast.
            symbols_to_remove = [sym_id for sym_id in self.code_index if sym_id.startswith(f"{rel_path}::")]
            for sym_id in symbols_to_remove:
                self.code_index.pop(sym_id, None)

            # Clean references originating from this file
            for sym_id in list(self.reference_index.keys()):
                self.reference_index[sym_id] = [ref for ref in self.reference_index[sym_id] if ref.get("file_path") != rel_path]
                if not self.reference_index[sym_id]:
                    self.reference_index.pop(sym_id, None)

            # Parse new symbols
            new_symbols = ASTIndexer.index_file(self.workspace_dir, rel_path)
            symbol_ids = []
            for sym in new_symbols:
                self.code_index[sym.id] = {
                    "name": sym.name,
                    "type": sym.type,
                    "file_path": sym.file_path,
                    "start_line": sym.start_line,
                    "end_line": sym.end_line,
                    "parent": sym.parent,
                    "docstring": sym.docstring,
                    "snippet": sym.snippet
                }
                symbol_ids.append(sym.id)

            # Save File Ownership Metadata
            if rel_path in updated_metadata["files"]:
                updated_metadata["files"][rel_path]["symbols"] = symbol_ids

            # Generate File Summary
            classes = [s.name for s in new_symbols if s.type == "class"]
            functions = [s.name for s in new_symbols if s.type == "function" and not s.parent]
            summary_parts = []
            if classes:
                summary_parts.append(f"Classes: {', '.join(classes)}")
            if functions:
                summary_parts.append(f"Functions: {', '.join(functions)}")

            summary_text = ". ".join(summary_parts)
            self.file_summaries[rel_path] = {
                "summary": summary_text or "Utility/Config file.",
                "hash": updated_metadata["files"].get(rel_path, {}).get("hash", ""),
                "last_modified": updated_metadata["files"].get(rel_path, {}).get("last_modified", 0.0),
            }

        # 3. Update Dependency Graph (All python files)
        all_py_files = [f for f in updated_metadata["files"].keys() if f.endswith(".py")]
        from core.code_intelligence.dependency_resolver import DependencyResolver
        forward_graph, reverse_graph = DependencyResolver.build_graphs(self.workspace_dir, all_py_files)

        self.dependency_graph = {
            "forward": forward_graph,
            "reverse": reverse_graph
        }

        # 4. Extract references from reindexed files
        for rel_path in to_reindex:
            if rel_path.endswith(".py"):
                file_refs = self._extract_references_from_file(rel_path)
                for sym_id, line_no in file_refs:
                    if sym_id not in self.reference_index:
                        self.reference_index[sym_id] = []
                    if not any(r["file_path"] == rel_path and r["line_no"] == line_no for r in self.reference_index[sym_id]):
                        self.reference_index[sym_id].append({
                            "file_path": rel_path,
                            "line_no": line_no
                        })

        # Save all json files
        self.save_json_file(self.metadata_file, updated_metadata)
        self.save_json_file(self.code_index_file, self.code_index)
        self.save_json_file(self.dependency_graph_file, self.dependency_graph)
        self.save_json_file(self.file_summaries_file, self.file_summaries)
        self.save_json_file(self.reference_index_file, self.reference_index)

    def _extract_references_from_file(self, rel_path: str) -> List[Tuple[str, int]]:
        """Scan AST of a file and find references to any known symbol in the codebase."""
        import ast
        full_path = os.path.join(self.workspace_dir, rel_path)
        refs = []
        if not os.path.exists(full_path):
            return refs
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            tree = ast.parse(content, filename=full_path)

            # Map symbol name -> list of symbol IDs
            symbol_name_to_ids = {}
            for sym_id, sym_info in self.code_index.items():
                name = sym_info["name"]
                if name not in symbol_name_to_ids:
                    symbol_name_to_ids[name] = []
                symbol_name_to_ids[name].append(sym_id)

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                if isinstance(node, ast.Name):
                    name = node.id
                    if name in symbol_name_to_ids:
                        same_file_ids = [sid for sid in symbol_name_to_ids[name] if sid.startswith(f"{rel_path}::")]
                        if same_file_ids:
                            for sid in same_file_ids:
                                refs.append((sid, node.lineno))
                        else:
                            for sid in symbol_name_to_ids[name]:
                                refs.append((sid, node.lineno))
                elif isinstance(node, ast.Attribute):
                    name = node.attr
                    if name in symbol_name_to_ids:
                        for sid in symbol_name_to_ids[name]:
                            refs.append((sid, node.lineno))
        except Exception as e:
            logger.warning(f"Error extracting references from {rel_path}: {e}")
        return list(set(refs))

