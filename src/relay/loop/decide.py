"""The developer's decision on a drift card: `accept [reason]`, `redirect <text>`,
`rule <spec>` or `reject`, asked through a `Console`."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from relay.domain import Accept, MakeRule, Redirect, Reject, SteerDecision
from relay.loop.rules import apply_rule

PROMPT = "accept [reason] | redirect <text> | rule <spec> | reject > "


@dataclass
class Console:
    ask: Callable[[str], str]
    show: Callable[[str], None]

    def confirm(self, question: str) -> bool:
        return self.ask(question).strip().lower() in {"y", "yes"}


def parse_decision(line: str) -> SteerDecision | None:
    """Read `accept [reason]`, `redirect <text>`, `rule <spec>` or `reject`."""
    word, _, rest = line.strip().partition(" ")
    rest = rest.strip().strip("\"'").strip()
    if word == "accept":
        return Accept(reason=rest or None)
    if word == "reject" and not rest:
        return Reject()
    if word == "redirect" and rest:
        return Redirect(text=rest)
    if word == "rule" and rest:
        return MakeRule(spec=rest)
    return None


def unrecorded(decision: SteerDecision) -> None:
    return None


def decide(
    repo: Path,
    console: Console,
    needs_reason: bool,
    rules: list[str],
    record: Callable[[SteerDecision], None] = unrecorded,
    can_redirect: bool = True,
) -> Accept | Redirect | Reject:
    """Ask until the developer accepts, redirects or rejects; write rules on the way.

    `record` is called with each rule once written, and with the final decision.
    `can_redirect` is False once the token budget is spent.
    """
    while True:
        decision = parse_decision(console.ask(PROMPT))
        if decision is None:
            console.show("Say: accept [reason], redirect <text>, rule <spec> or reject.")
        elif isinstance(decision, MakeRule):
            apply_rule(repo, decision.spec, console.confirm, console.show)
            rules.append(decision.spec)
            record(decision)
        elif isinstance(decision, Accept) and needs_reason and decision.reason is None:
            console.show("This card has blocking findings or failed checks: accept <reason>.")
        elif isinstance(decision, Redirect) and not can_redirect:
            console.show("The packet's token budget is spent: accept, rule or reject.")
        else:
            record(decision)
            return decision
