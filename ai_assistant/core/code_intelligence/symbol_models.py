from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class SymbolInfo:
    id: str  # Unique symbol ID: e.g. "path/to/file.py::ClassName" or "path/to/file.py::func_name"
    name: str  # Name of class/function/constant
    type: str  # "class", "function", or "constant"
    file_path: str  # Relative file path in workspace
    start_line: int
    end_line: int
    parent: Optional[str] = None  # Parent class name if this is a method
    docstring: str = ""
    snippet: str = ""

@dataclass
class FileSummary:
    file_path: str
    summary: str = ""
    hash: str = ""
    last_modified: float = 0.0
    imports: List[str] = field(default_factory=list)
