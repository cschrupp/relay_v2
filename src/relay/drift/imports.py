"""Import graph between the top-level packages under a root, and the cycles in it.

A node is a top-level subpackage or module directly under the root package. Every
import counts, including those inside functions and `if TYPE_CHECKING:` blocks,
because each one is a dependency someone has to reason about.
"""

import ast
from collections.abc import Iterator, Mapping

Graph = dict[str, set[str]]


def module_location(relative_path: str) -> tuple[list[str], bool]:
    """Split a path relative to the root into module parts and whether it is an __init__."""
    parts = relative_path.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        return parts[:-1], True
    return parts, False


def imported_names(tree: ast.Module, package: str, relative_path: str) -> Iterator[str]:
    """Yield the absolute dotted names a module imports, with relative imports resolved."""
    parts, is_init = module_location(relative_path)
    containing = [package, *(parts if is_init else parts[:-1])]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = containing[: len(containing) - (node.level - 1)]
                base = ".".join([*anchor, *([node.module] if node.module else [])])
            yield base
            yield from (f"{base}.{alias.name}" for alias in node.names)


def top_level_graph(trees: Mapping[str, ast.Module], package: str) -> Graph:
    """Return edges between top-level nodes, given parsed modules keyed by path under the root."""
    nodes = {module_location(path)[0][0] for path in trees if module_location(path)[0]}
    graph: Graph = {node: set() for node in nodes}
    for path, tree in trees.items():
        parts, _ = module_location(path)
        if not parts:
            continue
        for name in imported_names(tree, package, path):
            pieces = name.split(".")
            if len(pieces) > 1 and pieces[0] == package and pieces[1] in nodes:
                graph[parts[0]].add(pieces[1])
        graph[parts[0]].discard(parts[0])
    return graph


def import_cycles(graph: Graph) -> list[list[str]]:
    """Return each strongly connected component with more than one node, largest first."""
    index: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(node: str) -> None:
        index[node] = lowlink[node] = len(index)
        stack.append(node)
        on_stack.add(node)
        for target in sorted(graph.get(node, ())):
            if target not in index:
                visit(target)
                lowlink[node] = min(lowlink[node], lowlink[target])
            elif target in on_stack:
                lowlink[node] = min(lowlink[node], index[target])
        if lowlink[node] == index[node]:
            component: list[str] = []
            while not component or component[-1] != node:
                component.append(stack.pop())
                on_stack.discard(component[-1])
            if len(component) > 1:
                components.append(sorted(component))

    for node in sorted(graph):
        if node not in index:
            visit(node)
    return sorted(components, key=lambda component: (-len(component), component))
