"""Structural drift metrics for a repository at one commit."""

import ast
from dataclasses import dataclass
from pathlib import Path

from relay.drift.functions import OversizedFunction, oversized_functions
from relay.drift.git import commit_date, list_files, read_files, resolve_commit
from relay.drift.imports import import_cycles, top_level_graph

DEFAULT_BUDGET = 80
LARGEST_FILES = 10
TEST_DIRECTORIES = frozenset({"tests", "test"})


class DriftError(ValueError):
    """The repository cannot be measured as asked."""


@dataclass(frozen=True)
class FileSize:
    path: str
    lines: int


@dataclass(frozen=True)
class DriftReport:
    commit: str
    date: str
    root: str
    budget: int
    cycles: tuple[tuple[str, ...], ...]
    oversized: tuple[OversizedFunction, ...]
    source_files: int
    source_lines: int
    test_files: int
    test_lines: int
    largest_files: tuple[FileSize, ...]
    unparsable: tuple[str, ...]


def count_lines(text: str) -> int:
    """Count physical lines, including a last line without a newline."""
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def is_test_path(path: str) -> bool:
    """Whether a Python file is a test file, by directory or file name."""
    *directories, name = path.split("/")
    in_test_directory = any(directory in TEST_DIRECTORIES for directory in directories)
    return in_test_directory or name.startswith("test_") or name.endswith("_test.py")


def detect_root(paths: list[str]) -> str:
    """Return src/PKG when exactly one package sits directly under src/."""
    packages = sorted(
        path.split("/")[1]
        for path in paths
        if path.startswith("src/") and path.endswith("/__init__.py") and path.count("/") == 2
    )
    if len(packages) != 1:
        found = ", ".join(packages) or "none"
        raise DriftError(f"cannot pick a root package under src/ (found: {found}); pass --root")
    return f"src/{packages[0]}"


def parse_sources(texts: dict[str, str], root: str) -> tuple[dict[str, ast.Module], list[str]]:
    """Parse files under root, keyed by path relative to it; also return unparsable paths."""
    trees: dict[str, ast.Module] = {}
    unparsable: list[str] = []
    for path, text in texts.items():
        try:
            trees[path.removeprefix(f"{root}/")] = ast.parse(text, filename=path)
        except SyntaxError, ValueError:
            unparsable.append(path)
    return trees, unparsable


def build_report(
    repo: Path, rev: str = "HEAD", root: str | None = None, budget: int = DEFAULT_BUDGET
) -> DriftReport:
    """Measure the repository as committed at rev, reading git objects only."""
    if budget < 1:
        raise DriftError("the line budget must be at least 1")
    commit = resolve_commit(repo, rev)
    python_files = [path for path in list_files(repo, commit) if path.endswith(".py")]
    root = (root or detect_root(python_files)).strip("/").removeprefix("./")
    source_paths = [path for path in python_files if path.startswith(f"{root}/")]
    if not source_paths:
        raise DriftError(f"no Python files under {root} at {commit[:12]}")
    test_paths = [
        path for path in python_files if is_test_path(path) and not path.startswith(f"{root}/")
    ]
    texts = read_files(repo, commit, source_paths + test_paths)
    sources = {path: texts[path] for path in source_paths}
    trees, unparsable = parse_sources(sources, root)
    oversized = [
        found
        for relative, tree in trees.items()
        for found in oversized_functions(tree, f"{root}/{relative}", budget)
    ]
    sizes = sorted(
        (FileSize(path, count_lines(text)) for path, text in sources.items()),
        key=lambda size: (-size.lines, size.path),
    )
    return DriftReport(
        commit=commit,
        date=commit_date(repo, commit),
        root=root,
        budget=budget,
        cycles=tuple(
            tuple(cycle) for cycle in import_cycles(top_level_graph(trees, root.split("/")[-1]))
        ),
        oversized=tuple(
            sorted(oversized, key=lambda found: (-found.lines, found.path, found.line))
        ),
        source_files=len(source_paths),
        source_lines=sum(size.lines for size in sizes),
        test_files=len(test_paths),
        test_lines=sum(count_lines(texts[path]) for path in test_paths),
        largest_files=tuple(sizes[:LARGEST_FILES]),
        unparsable=tuple(sorted(unparsable)),
    )
