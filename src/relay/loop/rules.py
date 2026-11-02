"""Turn a steering correction into a rule ("make this a rule").

Every rule is appended to `.relay/rules.yaml` in the developer's working tree. A rule of
the form "<module> must not import <module>" also becomes a two-layer import-linter
contract (the imported module above the importer), which is shown to the developer and
appended to `.importlinter` only after they confirm. Nothing is committed: the developer
reviews and commits rule changes themselves.
"""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import yaml

from relay.domain import parse_rules
from relay.domain.rules import RULES_PATH
from relay.drift.card import LAYER_CONFIG

IMPORT_RULE = re.compile(r"^\s*([A-Za-z_][\w.]*)\s+must not import\s+([A-Za-z_][\w.]*)\s*$")


def append_rule_note(repo: Path, text: str) -> Path:
    """Add the rule to `.relay/rules.yaml`, keeping everything already there."""
    path = repo / RULES_PATH
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    parse_rules(existing)
    loaded: object = yaml.safe_load(existing) if existing else None
    data = dict(cast(dict[str, Any], loaded)) if isinstance(loaded, dict) else {}
    notes = list(cast(list[object], data.get("rules") or []))
    data["rules"] = [*notes, {"text": text}]
    updated = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    parse_rules(updated)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    return path


def import_contract(spec: str) -> str | None:
    """The `.importlinter` section for "<a> must not import <b>", or None for other rules."""
    match = IMPORT_RULE.match(spec)
    if match is None:
        return None
    importer, imported = match.groups()
    name = f"{importer} must not import {imported}"
    key = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    layers = f"    {imported}\n    {importer}\n"
    return f"\n[importlinter:contract:{key}]\nname = {name}\ntype = layers\nlayers =\n{layers}"


def apply_rule(
    repo: Path, spec: str, confirm: Callable[[str], bool], show: Callable[[str], None]
) -> list[Path]:
    """Write the rule; return the files changed."""
    changed = [append_rule_note(repo, spec)]
    show(f"Added to {RULES_PATH}: {spec}")
    contract = import_contract(spec)
    if contract is None:
        return changed
    show(f"Proposed addition to {LAYER_CONFIG}:{contract}")
    if confirm(f"Append this contract to {LAYER_CONFIG}? [y/N] "):
        path = repo / LAYER_CONFIG
        with path.open("a", encoding="utf-8") as file:
            file.write(contract)
        changed.append(path)
        show(f"Appended to {LAYER_CONFIG}.")
    return changed
