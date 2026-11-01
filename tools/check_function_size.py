"""Fail when any function or method is longer than the line budget.

Usage: python tools/check_function_size.py [PATH ...]   (default: src)
"""

import ast
import sys
from pathlib import Path

MAX_FUNCTION_LINES = 80


def oversized_functions(path: Path, limit: int) -> list[tuple[int, str, int]]:
    """Return (line, name, length) for each function in a file longer than limit."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            end = node.end_lineno if node.end_lineno is not None else node.lineno
            length = end - node.lineno + 1
            if length > limit:
                found.append((node.lineno, node.name, length))
    return sorted(found)


def main(argv: list[str]) -> int:
    roots = [Path(arg) for arg in argv] or [Path("src")]
    failures = 0
    for root in roots:
        files = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in files:
            for line, name, length in oversized_functions(path, MAX_FUNCTION_LINES):
                print(f"{path}:{line}: {name} is {length} lines (budget {MAX_FUNCTION_LINES})")
                failures += 1
    if failures:
        print(f"{failures} function(s) over the {MAX_FUNCTION_LINES}-line budget")
        return 1
    print(f"All functions within the {MAX_FUNCTION_LINES}-line budget")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
