"""Functions longer than a line budget.

Length is `end_lineno - lineno + 1` for every `def` and `async def`, nested ones
included: the same rule as `tools/check_function_size.py`.
"""

import ast
from collections.abc import Iterator
from dataclasses import dataclass

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class OversizedFunction:
    path: str
    line: int
    name: str
    lines: int


def named_functions(node: ast.AST, prefix: str = "") -> Iterator[tuple[str, FunctionNode]]:
    """Yield (qualified name, node) for every function under node, nested ones included."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, FunctionNode):
            name = f"{prefix}{child.name}"
            yield name, child
            yield from named_functions(child, f"{name}.")
        elif isinstance(child, ast.ClassDef):
            yield from named_functions(child, f"{prefix}{child.name}.")
        else:
            yield from named_functions(child, prefix)


def oversized_functions(tree: ast.Module, path: str, budget: int) -> list[OversizedFunction]:
    """Return the functions in one parsed file that are longer than budget lines."""
    found: list[OversizedFunction] = []
    for name, node in named_functions(tree):
        end = node.end_lineno if node.end_lineno is not None else node.lineno
        length = end - node.lineno + 1
        if length > budget:
            found.append(OversizedFunction(path, node.lineno, name, length))
    return found
