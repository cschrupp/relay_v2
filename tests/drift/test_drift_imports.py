import ast

from relay.drift.imports import import_cycles, top_level_graph


def graph_of(files: dict[str, str]) -> dict[str, set[str]]:
    return top_level_graph({path: ast.parse(text) for path, text in files.items()}, "pkg")


def test_absolute_imports_form_a_cycle() -> None:
    graph = graph_of(
        {
            "a/__init__.py": "import pkg.b.core\n",
            "b/__init__.py": "",
            "b/core.py": "from pkg.a import thing\n",
        }
    )

    assert graph == {"a": {"b"}, "b": {"a"}}
    assert import_cycles(graph) == [["a", "b"]]


def test_chain_without_back_edge_has_no_cycle() -> None:
    graph = graph_of(
        {
            "a/__init__.py": "from pkg import b\n",
            "b/__init__.py": "from pkg.c import x\n",
            "c/__init__.py": "import os\n",
        }
    )

    assert import_cycles(graph) == []


def test_relative_imports_resolve_against_the_containing_package() -> None:
    graph = graph_of(
        {
            "a/__init__.py": "",
            "a/sub/mod.py": "from ...b import x\n",
            "a/sub/__init__.py": "from .. import helpers\n",
            "a/helpers.py": "",
            "b/__init__.py": "from .. import a\n",
        }
    )

    assert graph["a"] == {"b"}
    assert graph["b"] == {"a"}


def test_function_local_imports_and_top_level_modules_count() -> None:
    graph = graph_of(
        {
            "settings.py": "def load():\n    from pkg.store import db\n",
            "store/__init__.py": "from pkg.settings import load\n",
        }
    )

    assert import_cycles(graph) == [["settings", "store"]]


def test_self_imports_and_foreign_packages_are_ignored() -> None:
    graph = graph_of(
        {
            "a/__init__.py": "from pkg.a import inner\nimport other.b\nfrom pkg import *\n",
            "a/inner.py": "from . import sibling\n",
        }
    )

    assert graph == {"a": set()}


def test_separate_components_are_reported_largest_first() -> None:
    graph = {"a": {"b"}, "b": {"a"}, "x": {"y"}, "y": {"z"}, "z": {"x"}, "solo": set()}

    assert import_cycles(graph) == [["x", "y", "z"], ["a", "b"]]
