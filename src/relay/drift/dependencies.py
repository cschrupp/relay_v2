"""Declared dependencies in a `pyproject.toml`: project, optional and dependency groups."""

import re
import tomllib

NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalized_name(requirement: str) -> str | None:
    """The PEP 503 normalized distribution name of a requirement string."""
    match = NAME.match(requirement)
    return re.sub(r"[-_.]+", "-", match.group(1)).lower() if match else None


def declared_dependencies(text: str | None) -> set[str]:
    """Names of every dependency declared in pyproject text; empty when absent or invalid."""
    if text is None:
        return set()
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return set()
    project = data.get("project", {})
    requirements: list[object] = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        requirements += group
    for group in data.get("dependency-groups", {}).values():
        requirements += group
    names = {normalized_name(item) for item in requirements if isinstance(item, str)}
    return {name for name in names if name}
