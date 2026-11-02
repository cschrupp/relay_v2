"""Layer violations against a repository's own `.importlinter` layers contracts.

Supported: `layers` contracts with `name`, `layers` (`|` for independent siblings, `:` for
siblings that may import each other, parentheses for optional layers) and `containers`.
Any other contract type or option is reported as unsupported and that contract is not
checked, so nothing is silently ignored. Only direct imports are checked; import-linter
also follows indirect chains.
"""

import ast
import configparser
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from relay.drift.imports import imported_names, module_location

SUPPORTED_OPTIONS = frozenset({"name", "type", "layers", "containers"})


@dataclass(frozen=True)
class Level:
    modules: tuple[str, ...]
    independent: bool


@dataclass(frozen=True)
class LayerContract:
    name: str
    levels: tuple[Level, ...]


@dataclass(frozen=True)
class Contracts:
    root_package: str | None
    layers: tuple[LayerContract, ...]
    unsupported: tuple[str, ...]


@dataclass(frozen=True)
class Violation:
    contract: str
    importer: str
    imported: str
    path: str


def parse_level(line: str, container: str | None) -> Level:
    independent = ":" not in line
    names = [name.strip().strip("()") for name in line.replace(":", "|").split("|")]
    prefix = f"{container}." if container else ""
    return Level(tuple(f"{prefix}{name}" for name in names if name), independent)


def parse_contracts(text: str) -> Contracts:
    """Read the layers contracts in an `.importlinter` file."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    root_package = parser.get("importlinter", "root_package", fallback=None)
    layers: list[LayerContract] = []
    unsupported: list[str] = []
    for section in parser.sections():
        if not section.startswith("importlinter:contract:"):
            continue
        options = parser[section]
        name = options.get("name") or section.removeprefix("importlinter:contract:")
        extra = sorted(set(options) - SUPPORTED_OPTIONS)
        if options.get("type") != "layers" or extra:
            kind = options.get("type")
            reason = f"type {kind}" if kind != "layers" else f"option {', '.join(extra)}"
            unsupported.append(f"contract {name!r} not checked: {reason} is not supported")
            continue
        lines = [line for line in options.get("layers", "").splitlines() if line.strip()]
        containers = options.get("containers", "").split() or [None]
        for container in containers:
            levels = tuple(parse_level(line, container) for line in lines)
            layers.append(LayerContract(name, levels))
    return Contracts(root_package, tuple(layers), tuple(unsupported))


def locate(name: str, contract: LayerContract) -> tuple[int, str] | None:
    """Return (level index, layer module) that contains the dotted name, if any."""
    for index, level in enumerate(contract.levels):
        for module in level.modules:
            if name == module or name.startswith(f"{module}."):
                return index, module
    return None


def is_violation(contract: LayerContract, importer: str, imported: str) -> str | None:
    """Return the layer module the importer may not import, or None when allowed."""
    source = locate(importer, contract)
    target = locate(imported, contract)
    if source is None or target is None or source[1] == target[1]:
        return None
    if target[0] < source[0]:
        return target[1]
    if target[0] == source[0] and contract.levels[source[0]].independent:
        return target[1]
    return None


def module_imports(
    trees: Mapping[str, ast.Module], package: str, root: str
) -> Iterator[tuple[str, str, str]]:
    """Yield (importer module, imported name, file path) for every import under the root."""
    for relative, tree in trees.items():
        parts, _ = module_location(relative)
        importer = ".".join([package, *parts])
        for name in imported_names(tree, package, relative):
            yield importer, name, f"{root}/{relative}"


def layer_violations(
    contracts: Contracts, trees: Mapping[str, ast.Module], package: str, root: str
) -> set[Violation]:
    """Every direct import that breaks a layers contract."""
    found: set[Violation] = set()
    for importer, name, path in module_imports(trees, package, root):
        for contract in contracts.layers:
            forbidden = is_violation(contract, importer, name)
            if forbidden is not None:
                layer = locate(importer, contract)
                source = layer[1] if layer else importer
                found.add(Violation(contract.name, source, forbidden, path))
    return found
