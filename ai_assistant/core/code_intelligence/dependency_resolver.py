import ast
import os
import logging
from typing import Dict, Any, List, Set, Tuple

logger = logging.getLogger(__name__)

class DependencyResolver:
    @staticmethod
    def extract_imports_from_file(workspace_dir: str, rel_path: str) -> List[str]:
        """Extract import strings from a file's AST tree."""
        full_path = os.path.join(workspace_dir, rel_path)
        imports = []
        
        if not os.path.exists(full_path) or not rel_path.endswith(".py"):
            return imports
            
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            tree = ast.parse(content, filename=full_path)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append((None, alias.name, 0))
                elif isinstance(node, ast.ImportFrom):
                    imports.append((node.module, [alias.name for alias in node.names], node.level))
        except Exception as e:
            logger.warning(f"Error extracting imports from {rel_path}: {e}")
            
        resolved = []
        for imp_info in imports:
            resolved_paths = DependencyResolver._resolve_import(workspace_dir, rel_path, imp_info)
            for path in resolved_paths:
                resolved.append(path)
                
        return sorted(list(set(resolved)))

    @staticmethod
    def _resolve_import(workspace_dir: str, current_file: str, imp_info: Tuple[str, Any, int]) -> List[str]:
        """Resolve import node info into actual relative workspace file paths."""
        module_name, names, level = imp_info
        resolved_files = []
        
        # Determine base directory for relative imports
        curr_dir = os.path.dirname(current_file)
        
        if level > 0:
            # Relative import: e.g. from ..core import executor
            parts = curr_dir.replace("\\", "/").split("/")
            if level <= len(parts):
                # Go up level - 1 directories
                base_parts = parts[: len(parts) - level + 1]
                base_dir = "/".join(base_parts)
            else:
                base_dir = ""
                
            # Construct the relative module path
            mod_path = ""
            if module_name:
                mod_path = module_name.replace(".", "/")
                
            possible_paths = [
                os.path.join(base_dir, mod_path + ".py"),
                os.path.join(base_dir, mod_path, "__init__.py")
            ]
            
            # If names is a list (e.g. from ..utils import helper1, helper2), they could be files
            if isinstance(names, list):
                for name in names:
                    possible_paths.append(os.path.join(base_dir, mod_path, name + ".py"))
                    possible_paths.append(os.path.join(base_dir, mod_path, name, "__init__.py"))
        else:
            # Absolute import: e.g. import core.executor or from core import executor
            mod_path = ""
            if module_name:
                mod_path = module_name.replace(".", "/")
            elif isinstance(names, str):
                mod_path = names.replace(".", "/")
                
            possible_paths = [
                os.path.join(mod_path + ".py"),
                os.path.join(mod_path, "__init__.py")
            ]
            
            if isinstance(names, list):
                for name in names:
                    possible_paths.append(os.path.join(mod_path, name + ".py"))
                    possible_paths.append(os.path.join(mod_path, name, "__init__.py"))
                    
        # Check which of the possible relative paths exist in workspace_dir
        for rel in possible_paths:
            normalized_rel = os.path.normpath(rel).replace("\\", "/")
            # Prevent going outside workspace
            if normalized_rel.startswith("..") or normalized_rel.startswith("/"):
                continue
            full_check = os.path.join(workspace_dir, normalized_rel)
            if os.path.isfile(full_check):
                resolved_files.append(normalized_rel)
                
        return resolved_files

    @staticmethod
    def build_graphs(workspace_dir: str, files: List[str]) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
        """Build forward and reverse dependency graphs for the list of workspace files."""
        forward_graph: Dict[str, List[str]] = {}
        reverse_graph: Dict[str, List[str]] = {}
        
        # Initialize graphs
        for f in files:
            forward_graph[f] = []
            reverse_graph[f] = []
            
        for f in files:
            if f.endswith(".py"):
                imports = DependencyResolver.extract_imports_from_file(workspace_dir, f)
                for imp in imports:
                    if imp in forward_graph: # Only track dependencies within the project
                        forward_graph[f].append(imp)
                        if imp not in reverse_graph:
                            reverse_graph[imp] = []
                        if f not in reverse_graph[imp]:
                            reverse_graph[imp].append(f)
                            
        return forward_graph, reverse_graph

    @staticmethod
    def get_transitive_context(forward_graph: Dict[str, List[str]], entry_file: str, max_depth: int = 3) -> List[str]:
        """Collect all files imported transitively from an entry file up to a certain depth (prevents infinite recursion on circular imports)."""
        visited: Set[str] = set()
        
        def _dfs(node: str, depth: int):
            if depth > max_depth or node in visited:
                return
            visited.add(node)
            for neighbor in forward_graph.get(node, []):
                _dfs(neighbor, depth + 1)
                
        _dfs(entry_file, 1)
        # Exclude entry_file from dependencies list
        if entry_file in visited:
            visited.remove(entry_file)
        return sorted(list(visited))
