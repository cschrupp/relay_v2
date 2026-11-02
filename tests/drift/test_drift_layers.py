import ast

from relay.drift.dependencies import declared_dependencies
from relay.drift.layers import Violation, layer_violations, parse_contracts

CONFIG = """
[importlinter]
root_package = app

[importlinter:contract:layers]
name = App layers
type = layers
layers =
    app.cli
    app.drift | app.store
    app.web : app.api
    (app.domain)

[importlinter:contract:forbid]
name = No requests
type = forbidden
source_modules = app
forbidden_modules = requests

[importlinter:contract:ignored]
name = With exceptions
type = layers
layers = app.a
ignore_imports = app.a -> app.b
"""


def violations(files: dict[str, str]) -> set[tuple[str, str]]:
    trees = {path: ast.parse(text) for path, text in files.items()}
    found = layer_violations(parse_contracts(CONFIG), trees, "app", "src/app")
    return {(v.importer, v.imported) for v in found}


def test_unsupported_contracts_are_reported_not_ignored() -> None:
    contracts = parse_contracts(CONFIG)

    assert [c.name for c in contracts.layers] == ["App layers"]
    assert contracts.root_package == "app"
    assert contracts.unsupported == (
        "contract 'No requests' not checked: type forbidden is not supported",
        "contract 'With exceptions' not checked: option ignore_imports is not supported",
    )


def test_lower_layer_importing_higher_is_a_violation() -> None:
    assert violations({"domain/x.py": "from app.cli import main\n"}) == {("app.domain", "app.cli")}
    assert violations({"cli/x.py": "from app.domain import x\n"}) == set()


def test_independent_siblings_may_not_import_each_other() -> None:
    assert violations({"drift/x.py": "import app.store.db\n"}) == {("app.drift", "app.store")}


def test_colon_siblings_may_import_each_other() -> None:
    assert violations({"web/x.py": "from app.api import routes\n"}) == set()


def test_relative_imports_and_unlisted_modules() -> None:
    assert violations({"store/x.py": "from ..cli import main\n"}) == {("app.store", "app.cli")}
    assert violations({"other/x.py": "from app.cli import main\n"}) == set()


def test_containers_prefix_layer_names() -> None:
    config = """
[importlinter]
root_package = app
[importlinter:contract:c]
name = Contained
type = layers
containers = app.one app.two
layers =
    high
    low
"""
    trees = {"two/low.py": ast.parse("from app.two import high\n")}
    found = layer_violations(parse_contracts(config), trees, "app", "src/app")
    assert found == {Violation("Contained", "app.two.low", "app.two.high", "src/app/two/low.py")}


def test_declared_dependencies_cover_all_sections_and_normalize_names() -> None:
    text = """
[project]
dependencies = ["Pydantic>=2", "PyYAML ; python_version > '3'"]
[project.optional-dependencies]
web = ["httpx[http2]>=0.27"]
[dependency-groups]
dev = ["ruff", {include-group = "lint"}]
"""
    assert declared_dependencies(text) == {"pydantic", "pyyaml", "httpx", "ruff"}
    assert declared_dependencies(None) == set()
    assert declared_dependencies("not = [valid") == set()
