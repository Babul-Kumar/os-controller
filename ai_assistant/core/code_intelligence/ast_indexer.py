import ast
import logging
import os
from typing import Dict, Any, List, Optional
from core.code_intelligence.symbol_models import SymbolInfo

logger = logging.getLogger(__name__)

class ASTIndexer:
    @staticmethod
    def index_file(workspace_dir: str, rel_path: str) -> List[SymbolInfo]:
        """Parse a Python file using AST and extract all classes, functions, methods, and constants."""
        full_path = os.path.join(workspace_dir, rel_path)
        symbols: List[SymbolInfo] = []
        
        if not os.path.exists(full_path):
            return symbols
            
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                code_content = f.read()
                
            # Parse the code into an AST node tree
            tree = ast.parse(code_content, filename=full_path)
            lines = code_content.splitlines()
            
            # Helper to extract source snippets
            def get_snippet(start: int, end: int) -> str:
                # AST lines are 1-indexed, inclusive
                sub_lines = lines[start - 1 : end]
                return "\n".join(sub_lines)
                
            # Walk top-level nodes
            for node in tree.body:
                # ── 1. Top-Level Classes ──────────────────────────────────────
                if isinstance(node, ast.ClassDef):
                    start = node.lineno
                    # Calculate end line safely
                    end = getattr(node, "end_lineno", start)
                    doc = ast.get_docstring(node) or ""
                    symbol_id = f"{rel_path}::{node.name}"
                    
                    symbols.append(SymbolInfo(
                        id=symbol_id,
                        name=node.name,
                        type="class",
                        file_path=rel_path,
                        start_line=start,
                        end_line=end,
                        parent=None,
                        docstring=doc,
                        snippet=get_snippet(start, end)
                    ))
                    
                    # Extract methods/nested nodes inside Class body
                    for subnode in node.body:
                        if isinstance(subnode, ast.FunctionDef) or isinstance(subnode, ast.AsyncFunctionDef):
                            m_start = subnode.lineno
                            m_end = getattr(subnode, "end_lineno", m_start)
                            m_doc = ast.get_docstring(subnode) or ""
                            # Unique ID: file.py::ClassName::method_name
                            m_id = f"{rel_path}::{node.name}::{subnode.name}"
                            
                            symbols.append(SymbolInfo(
                                id=m_id,
                                name=subnode.name,
                                type="function",
                                file_path=rel_path,
                                start_line=m_start,
                                end_line=m_end,
                                parent=node.name,
                                docstring=m_doc,
                                snippet=get_snippet(m_start, m_end)
                            ))
                            
                # ── 2. Top-Level Functions ────────────────────────────────────
                elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    start = node.lineno
                    end = getattr(node, "end_lineno", start)
                    doc = ast.get_docstring(node) or ""
                    symbol_id = f"{rel_path}::{node.name}"
                    
                    symbols.append(SymbolInfo(
                        id=symbol_id,
                        name=node.name,
                        type="function",
                        file_path=rel_path,
                        start_line=start,
                        end_line=end,
                        parent=None,
                        docstring=doc,
                        snippet=get_snippet(start, end)
                    ))
                    
                # ── 3. Constants / Global Variables ───────────────────────────
                elif isinstance(node, ast.Assign):
                    # We look for simple assignments: UPPERCASE_NAME = value
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            name = target.id
                            if name.isupper():
                                start = node.lineno
                                end = getattr(node, "end_lineno", start)
                                symbol_id = f"{rel_path}::{name}"
                                
                                symbols.append(SymbolInfo(
                                    id=symbol_id,
                                    name=name,
                                    type="constant",
                                    file_path=rel_path,
                                    start_line=start,
                                    end_line=end,
                                    parent=None,
                                    docstring="",
                                    snippet=get_snippet(start, end)
                                ))
                                
        except SyntaxError as e:
            logger.warning(f"Syntax error while indexing {rel_path}: {e}")
        except Exception as e:
            logger.warning(f"Error indexing file {rel_path}: {e}")
            
        return symbols
