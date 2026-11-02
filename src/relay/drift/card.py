"""The drift card for one run: what changed from the packet's base to the result.

Findings, in card order: new import cycles, layer violations against the base
commit's `.importlinter`, functions over budget (new or grown), net lines against the
packet's estimate, files outside the allowed paths, new dependencies in
`pyproject.toml`, existing test files edited or deleted, and rule files changed
(`.importlinter`, anything under `.relay/`).

Net lines count Python files only, split into tests (by `is_test_path`) and source.
A count drifts when it exceeds the estimate by more than a quarter, and by at least
10 lines. Layer violations, rule file changes and tests that lose or change lines are blocking:
they break rules the developer set. A test file that only gains lines, and everything
else, is a warning for the developer to judge.
"""

import configparser
from pathlib import Path

from relay.domain import DriftCard, DriftFinding, LineEstimate, NetLines, WorkPacket
from relay.domain.card import Severity
from relay.drift.dependencies import declared_dependencies
from relay.drift.git import Change, diff_changes, read_optional, resolve_commit
from relay.drift.layers import Contracts, layer_violations, parse_contracts
from relay.drift.report import (
    DEFAULT_BUDGET,
    DriftError,
    DriftReport,
    build_report,
    is_test_path,
    source_trees,
)
from relay.drift.scope import path_allowed

LAYER_CONFIG = ".importlinter"
RULES_DIRECTORY = ".relay/"
PYPROJECT = "pyproject.toml"
MIN_ALLOWANCE = 10


def cycle_findings(before: DriftReport | None, after: DriftReport) -> list[DriftFinding]:
    old = [frozenset(cycle) for cycle in before.cycles] if before else []
    return [
        DriftFinding(kind="new_cycle", message=f"import cycle among {', '.join(cycle)}")
        for cycle in after.cycles
        if not any(old_cycle.issuperset(cycle) for old_cycle in old)
    ]


def function_findings(before: DriftReport | None, after: DriftReport) -> list[DriftFinding]:
    old = {(found.path, found.name): found.lines for found in before.oversized} if before else {}
    findings: list[DriftFinding] = []
    for found in after.oversized:
        previous = old.get((found.path, found.name))
        if previous is None or found.lines > previous:
            was = "" if previous is None else f", was {previous}"
            message = f"{found.name} is {found.lines} lines (budget {after.budget}{was})"
            findings.append(
                DriftFinding(
                    kind="oversized_function", message=message, path=found.path, line=found.line
                )
            )
    return findings


def net_lines(changes: list[Change]) -> NetLines:
    source = tests = 0
    for change in changes:
        if not change.path.endswith(".py") or change.added is None or change.deleted is None:
            continue
        delta = change.added - change.deleted
        if is_test_path(change.path):
            tests += delta
        else:
            source += delta
    return NetLines(source=source, tests=tests)


def line_findings(actual: NetLines, expected: LineEstimate) -> list[DriftFinding]:
    findings: list[DriftFinding] = []
    for label, got, wanted in (
        ("source", actual.source, expected.source),
        ("tests", actual.tests, expected.tests),
    ):
        if got > wanted + max(MIN_ALLOWANCE, wanted // 4):
            message = f"{label}: {got:+} net lines against {wanted} expected"
            findings.append(DriftFinding(kind="net_lines", message=message))
    return findings


def scope_findings(changes: list[Change], allowed: tuple[str, ...]) -> list[DriftFinding]:
    return [
        DriftFinding(
            kind="outside_scope",
            message=f"{change.path} is outside the allowed paths",
            path=change.path,
        )
        for change in changes
        if not path_allowed(change.path, allowed)
    ]


def test_findings(changes: list[Change]) -> list[DriftFinding]:
    """Existing test files changed: blocking when lines were removed or rewritten."""
    findings: list[DriftFinding] = []
    for change in changes:
        if change.status == "A" or not is_test_path(change.path):
            continue
        if change.status == "D":
            findings.append(test_finding(change.path, "existing test deleted", "blocking"))
        elif change.deleted == 0:
            findings.append(test_finding(change.path, "existing test file extended", "warning"))
        else:
            findings.append(test_finding(change.path, "existing test edited", "blocking"))
    return findings


def test_finding(path: str, message: str, severity: Severity) -> DriftFinding:
    return DriftFinding(kind="edited_test", message=message, severity=severity, path=path)


def is_rule_path(path: str) -> bool:
    """Files that hold the developer's rules: the layer contracts and `.relay/`."""
    return path == LAYER_CONFIG or path.startswith(RULES_DIRECTORY)


def rule_findings(changes: list[Change]) -> list[DriftFinding]:
    """Any change to a rule file is blocking: rules change only by the developer's hand."""
    verbs = {"A": "added", "D": "deleted"}
    return [
        DriftFinding(
            kind="edited_rule",
            severity="blocking",
            message=f"rule file {verbs.get(change.status, 'edited')}",
            path=change.path,
        )
        for change in changes
        if is_rule_path(change.path)
    ]


def dependency_findings(repo: Path, base: str, result: str) -> list[DriftFinding]:
    old = declared_dependencies(read_optional(repo, base, PYPROJECT))
    new = declared_dependencies(read_optional(repo, result, PYPROJECT)) - old
    return [
        DriftFinding(kind="new_dependency", message=f"new dependency: {name}", path=PYPROJECT)
        for name in sorted(new)
    ]


def read_contracts(repo: Path, base: str) -> Contracts | str | None:
    """The base commit's contracts, an error message when unreadable, or None when absent."""
    text = read_optional(repo, base, LAYER_CONFIG)
    if text is None:
        return None
    try:
        return parse_contracts(text)
    except configparser.Error as error:
        return f"{LAYER_CONFIG} cannot be read: {error}"


def layer_findings(repo: Path, base: str, result: str, root: str) -> list[DriftFinding]:
    contracts = read_contracts(repo, base)
    if contracts is None:
        return []
    if isinstance(contracts, str):
        return [DriftFinding(kind="unsupported_rule", message=contracts, path=LAYER_CONFIG)]
    findings = [
        DriftFinding(kind="unsupported_rule", message=message, path=LAYER_CONFIG)
        for message in contracts.unsupported
    ]
    package = root.split("/")[-1]
    if contracts.layers and contracts.root_package != package:
        message = f"root_package {contracts.root_package!r} is not {package!r}; layers not checked"
        return [
            *findings,
            DriftFinding(kind="unsupported_rule", message=message, path=LAYER_CONFIG),
        ]
    old = layer_violations(contracts, source_trees(repo, base, root), package, root)
    new = layer_violations(contracts, source_trees(repo, result, root), package, root) - old
    for violation in sorted(new, key=lambda item: (item.path, item.importer, item.imported)):
        message = f"{violation.importer} imports {violation.imported} ({violation.contract})"
        findings.append(
            DriftFinding(
                kind="layer_violation", severity="blocking", message=message, path=violation.path
            )
        )
    return findings


def build_card(
    repo: Path,
    packet: WorkPacket,
    result_rev: str,
    root: str | None = None,
    budget: int = DEFAULT_BUDGET,
) -> DriftCard:
    """Compare the packet's base commit with the result and collect every finding."""
    base = resolve_commit(repo, packet.base_sha)
    result = resolve_commit(repo, result_rev)
    after = build_report(repo, result, root, budget)
    try:
        before = build_report(repo, base, after.root, budget)
    except DriftError:
        before = None
    changes = diff_changes(repo, base, result)
    actual = net_lines(changes)
    findings = [
        *cycle_findings(before, after),
        *layer_findings(repo, base, result, after.root),
        *function_findings(before, after),
        *line_findings(actual, packet.expected_lines),
        *scope_findings(changes, packet.allowed_paths),
        *dependency_findings(repo, base, result),
        *test_findings(changes),
        *rule_findings(changes),
    ]
    return DriftCard(
        base_sha=base,
        result_sha=result,
        expected_lines=packet.expected_lines,
        actual_lines=actual,
        findings=tuple(findings),
    )
