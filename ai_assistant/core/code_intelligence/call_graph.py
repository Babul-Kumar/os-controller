import ast
import os
import logging
from typing import Dict, List, Set

logger = logging.getLogger(__name__)

class CallGraphExtractor:
    @staticmethod
    def extract_calls_from_file(workspace_dir: str, rel_path: str) -> Dict[str, List[str]]:
        """Parse a Python file and build a local call graph mapping function/class methods to other functions/methods they invoke."""
        full_path = os.path.join(workspace_dir, rel_path)
        call_map: Dict[str, List[str]] = {}
        
        if not os.path.exists(full_path) or not rel_path.endswith(".py"):
            return call_map
            
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            tree = ast.parse(content, filename=full_path)
            
            current_context = "global"
            
            class CallVisitor(ast.NodeVisitor):
                def __init__(self):
                    self.current_func = "global"
                    self.parent_class = None
                    
                def visit_ClassDef(self, node: ast.ClassDef):
                    old_class = self.parent_class
                    self.parent_class = node.name
                    self.generic_visit(node)
                    self.parent_class = old_class
                    
                def visit_FunctionDef(self, node: ast.FunctionDef):
                    old_func = self.current_func
                    
                    # Establish context name: e.g. "ClassName.method" or "function_name"
                    if self.parent_class:
                        context_name = f"{self.parent_class}.{node.name}"
                    else:
                        context_name = node.name
                        
                    self.current_func = context_name
                    if context_name not in call_map:
                        call_map[context_name] = []
                        
                    self.generic_visit(node)
                    self.current_func = old_func
                    
                def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
                    # Treat async functions exactly like normal functions
                    old_func = self.current_func
                    if self.parent_class:
                        context_name = f"{self.parent_class}.{node.name}"
                    else:
                        context_name = node.name
                        
                    self.current_func = context_name
                    if context_name not in call_map:
                        call_map[context_name] = []
                        
                    self.generic_visit(node)
                    self.current_func = old_func
                    
                def visit_Call(self, node: ast.Call):
                    called_name = None
                    
                    # 1. Simple call: func()
                    if isinstance(node.func, ast.Name):
                        called_name = node.func.id
                    # 2. Attribute call: obj.method()
                    elif isinstance(node.func, ast.Attribute):
                        if isinstance(node.func.value, ast.Name):
                            called_name = f"{node.func.value.id}.{node.func.attr}"
                        else:
                            called_name = node.func.attr
                            
                    if called_name:
                        # Append to current function calls list
                        if self.current_func not in call_map:
                            call_map[self.current_func] = []
                        if called_name not in call_map[self.current_func]:
                            call_map[self.current_func].append(called_name)
                            
                    self.generic_visit(node)
                    
            visitor = CallVisitor()
            visitor.visit(tree)
            
        except Exception as e:
            logger.warning(f"Error building call graph for {rel_path}: {e}")
            
        return call_map

    @staticmethod
    def trace_execution_flow(call_graph: Dict[str, List[str]], start_symbol: str, max_depth: int = 4) -> List[str]:
        """Trace the call hierarchy recursively starting from a given symbol (DFS) to build an execution path map."""
        visited: Set[str] = set()
        trace_lines: List[str] = []
        
        def _trace(symbol: str, depth: int):
            if depth > max_depth or symbol in visited:
                return
            visited.add(symbol)
            
            indent = "  " * (depth - 1)
            connector = " └── " if depth > 1 else ""
            trace_lines.append(f"{indent}{connector}{symbol}")
            
            # Look up matches: either exact, or matching method name if class prefix was omitted
            calls = call_graph.get(symbol, [])
            if not calls:
                # Try finding class methods if start_symbol was e.g. "start" and call_graph has "VoiceController.start"
                for context, context_calls in call_graph.items():
                    if context.endswith(f".{symbol}"):
                        calls = context_calls
                        break
                        
            for call in calls:
                _trace(call, depth + 1)
                
        _trace(start_symbol, 1)
        return trace_lines
