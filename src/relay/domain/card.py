"""The drift card: what a run changed, judged against the packet and the project rules."""

from typing import Annotated, Literal

from pydantic import Field

from relay.domain.base import Frozen, LineEstimate, NetLines, Sha, Text

FindingKind = Literal[
    "new_cycle",
    "layer_violation",
    "oversized_function",
    "net_lines",
    "outside_scope",
    "new_dependency",
    "edited_test",
    "unsupported_rule",
]
Severity = Literal["warning", "blocking"]


class DriftFinding(Frozen):
    kind: FindingKind
    message: Text
    severity: Severity = "warning"
    path: str | None = None
    line: Annotated[int, Field(ge=1)] | None = None


class DriftCard(Frozen):
    base_sha: Sha
    result_sha: Sha
    expected_lines: LineEstimate
    actual_lines: NetLines
    findings: tuple[DriftFinding, ...] = ()

    @property
    def blocking(self) -> bool:
        """Whether any finding prevents accepting the run as it is."""
        return any(finding.severity == "blocking" for finding in self.findings)
