"""What the developer and the agent read: the card, the prompts, the pull request body."""

from relay.domain import DriftCard, WorkPacket
from relay.loop.checks import CheckResult


def format_card(card: DriftCard, checks: list[CheckResult], failure: str | None) -> str:
    """The drift card with acceptance results, as plain text."""
    expected, actual = card.expected_lines, card.actual_lines
    lines = [
        f"Drift card {card.base_sha[:12]}..{card.result_sha[:12]}",
        f"  Net lines: source {actual.source:+} (expected {expected.source}), "
        f"tests {actual.tests:+} (expected {expected.tests})",
    ]
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


def pull_request_body(packet: WorkPacket, base_sha: str, card_text: str, reason: str | None) -> str:
    issue = f"Closes #{packet.issue}\n\n" if packet.issue else ""
    accepted = f"\n\nAccepted with blocking findings: {reason}" if reason else ""
    return (
        f"{issue}{packet.goal}\n\nBase: `{base_sha}`\n\n```\n{card_text}\n```{accepted}\n\n"
        "Opened by `relay run`."
    )
