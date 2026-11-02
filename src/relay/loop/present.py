"""What the developer and the agent read: the card, the prompts, the pull request body."""

import re
from dataclasses import dataclass
from decimal import Decimal

from relay.domain import DriftCard, WorkPacket
from relay.loop.checks import CheckResult

TITLE_LENGTH = 70
CLAUSE_END = re.compile(r":\s|\.\s|;\s|\n|\.$")


@dataclass(frozen=True)
class Spend:
    """What the agent used: one attempt's share, or a packet's total."""

    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal | None
    cost_source: str | None

    def text(self) -> str:
        cost = "cost not reported"
        if self.cost_usd is not None:
            cost = f"${self.cost_usd:.4f} ({self.cost_source})"
        return f"{self.model}, {self.input_tokens:,} tokens in, {self.output_tokens:,} out, {cost}"


def format_card(
    card: DriftCard, checks: list[CheckResult], failure: str | None, spend: Spend | None = None
) -> str:
    """The drift card with the agent's spend and the acceptance results, as plain text."""
    expected, actual = card.expected_lines, card.actual_lines
    lines = [
        f"Drift card {card.base_sha[:12]}..{card.result_sha[:12]}",
        f"  Net lines: source {actual.source:+} (expected {expected.source}), "
        f"tests {actual.tests:+} (expected {expected.tests})",
    ]
    if spend is not None:
        lines.append(f"  Agent: {spend.text()}")
    if failure:
        lines.append(f"  Agent failed: {failure}")
    for finding in card.findings:
        where = (
            f" [{finding.path}{f':{finding.line}' if finding.line else ''}]" if finding.path else ""
        )
        lines.append(f"  {finding.severity.upper():<8} {finding.kind}: {finding.message}{where}")
    if not card.findings:
        lines.append("  No drift findings.")
    for check in checks:
        lines.append(f"  {'PASS' if check.passed else 'FAIL'}     {check.command}")
        if not check.passed and check.tail:
            lines += [f"           {line}" for line in check.tail.splitlines()]
    return "\n".join(lines)


def initial_prompt(packet: WorkPacket) -> str:
    paths = "\n".join(f"- {path}" for path in packet.allowed_paths)
    commands = "\n".join(f"- `{command}`" for command in packet.acceptance_commands)
    return (
        f"{packet.goal}\n\n"
        f"Change only files matching:\n{paths}\n\n"
        f"Aim for about {packet.expected_lines.source} net lines of source and "
        f"{packet.expected_lines.tests} of tests.\n"
        "Do not edit existing tests or rule files (.importlinter, .relay/); they are "
        "read-only. Do not add dependencies.\n\n"
        f"The work is accepted when these pass:\n{commands}\n"
    )


def redirect_prompt(text: str, card_text: str) -> str:
    return (
        f"The developer redirects: {text}\n\n"
        f"Drift card of your last attempt:\n{card_text}\n\n"
        "Continue the same task on the same branch."
    )


def shorten(text: str, limit: int = TITLE_LENGTH) -> str:
    """At most `limit` characters, cut at a word boundary."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit + 1].rfind(" ")
    return text[:cut] if cut > 0 else text[:limit]


def pull_request_title(packet: WorkPacket, issue_title: str | None) -> str:
    """The issue's title when there is one, else the goal's first clause; under 70 chars."""
    if issue_title:
        return shorten(issue_title)
    return shorten(CLAUSE_END.split(packet.goal.strip(), maxsplit=1)[0])


def pull_request_body(
    packet: WorkPacket,
    base_sha: str,
    card_text: str,
    reason: str | None,
    total: Spend | None = None,
    attempts: int = 1,
) -> str:
    issue = f"Closes #{packet.issue}\n\n" if packet.issue else ""
    spent = f"Agent: {total.text()} over {attempts} attempt(s)\n\n" if total else ""
    accepted = f"\n\nAccepted with blocking findings: {reason}" if reason else ""
    return (
        f"{issue}{packet.goal}\n\nBase: `{base_sha}`\n\n{spent}```\n{card_text}\n```"
        f"{accepted}\n\nOpened by `relay run`."
    )
