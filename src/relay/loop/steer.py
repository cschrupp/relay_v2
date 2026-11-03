"""The steering loop: run one packet, show its drift card, apply the developer's decision.

attempt -> commit on the packet branch -> drift card + acceptance checks -> decision:
- `accept [reason]`  push the branch and open a pull request with the card; a card with
                     blocking findings or failed checks needs a reason, kept in the record;
- `redirect <text>`  resume the same session with the text and the card as feedback;
- `rule <spec>`      write a rule (see `relay.loop.rules`), then decide again;
- `reject`           drop the packet: worktree and branch are deleted.
The worktree is removed whenever the packet ends. If the loop is interrupted by an
error, the worktree and branch are left as they are for inspection.
With a `RunLog`, the run, every attempt and every decision are recorded as they happen
(see `relay.loop.record`).
"""

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from functools import partial
from pathlib import Path

from relay.domain import (
    Accept,
    DriftCard,
    MakeRule,
    Redirect,
    Reject,
    RunRecord,
    SteerDecision,
    WorkPacket,
)
from relay.domain.steer import Outcome
from relay.drift.card import build_card
from relay.loop.agent import Agent, TurnResult
from relay.loop.checks import CheckResult, run_checks
from relay.loop.present import (
    Spend,
    format_card,
    initial_prompt,
    pull_request_body,
    pull_request_title,
    redirect_prompt,
)
from relay.loop.publish import Publisher
from relay.loop.record import RunLog, recover_pending
from relay.loop.rules import apply_rule
from relay.loop.workspace import (
    Workspace,
    close_workspace,
    commit_attempt,
    has_work,
    open_workspace,
    protect,
    unprotect,
)
from relay.runtime.opencode import SessionSpec, Usage
from relay.store.runs import StoreError

PROMPT = "accept [reason] | redirect <text> | rule <spec> | reject > "
OUTCOMES: dict[str, Outcome] = {
    "accept": "accepted",
    "redirect": "redirected",
    "reject": "rejected",
}


@dataclass(frozen=True)
class AgentSettings:
    agent: str
    provider: str
    model: str


@dataclass
class PacketResult:
    base_sha: str
    branch: str
    records: list[RunRecord] = field(default_factory=lambda: [])
    cards: list[DriftCard] = field(default_factory=lambda: [])
    rules: list[str] = field(default_factory=lambda: [])
    pull_request: str | None = None
    title: str = ""


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
) -> Accept | Redirect | Reject:
    """Ask until the developer accepts, redirects or rejects; write rules on the way.

    `record` is called with each rule once written, and with the final decision.
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
        else:
            record(decision)
            return decision


def spent_since(now: Usage, before: Usage | None) -> tuple[int, int, Decimal | None]:
    """Input tokens, output tokens and cost of the latest turn (session usage is cumulative)."""
    if before is None:
        return now.input_tokens, now.output_tokens, now.cost_usd
    cost = None
    if now.cost_usd is not None and before.cost_usd is not None:
        cost = now.cost_usd - before.cost_usd
    return now.input_tokens - before.input_tokens, now.output_tokens - before.output_tokens, cost


def attempt(
    workspace: Workspace,
    packet: WorkPacket,
    agent: Agent,
    session: str,
    prompt: str,
    title: str,
    number: int,
) -> tuple[DriftCard, list[CheckResult], TurnResult]:
    """One agent turn with tests and rules read-only, committed and measured."""
    protected = protect(workspace)
    try:
        turn = agent.turn(session, prompt)
    finally:
        unprotect(protected)
    head = commit_attempt(workspace, f"relay: {title} (attempt {number})")
    card = build_card(workspace.path, packet, head)
    return card, run_checks(workspace.path, packet.acceptance_commands), turn


def record_failure(log: RunLog | None) -> None:
    """Close the run as failed; the error that ended it is the one to report."""
    if log is None or log.run_id is None:
        return
    with contextlib.suppress(StoreError):
        log.finish("failed")


def run_packet(
    repo: Path,
    packet: WorkPacket,
    settings: AgentSettings,
    agent: Agent,
    publisher: Publisher,
    console: Console,
    issue_titles: Callable[[int], str | None] | None = None,
    log: RunLog | None = None,
) -> PacketResult:
    """Run the packet until the developer accepts or rejects it.

    `issue_titles` looks up the packet's issue title for the commit and PR title. With
    `log`, runs a crash left pending are offered for cleanup first, then this run is
    recorded.
    """
    if log is not None:
        recover_pending(repo, log, console.confirm, console.show)
    issue_title = issue_titles(packet.issue) if issue_titles and packet.issue else None
    workspace = open_workspace(repo, packet)
    packet = packet.model_copy(update={"base_sha": workspace.base_sha})
    result = PacketResult(workspace.base_sha, workspace.branch)
    result.title = pull_request_title(packet, issue_title)
    console.show(f"Packet branch {workspace.branch} at {workspace.base_sha}")
    spec = SessionSpec(workspace.path, settings.agent, settings.provider, settings.model)
    try:
        if log is not None:
            log.start(packet, workspace.branch)
        session = agent.start(spec)
    except Exception:
        close_workspace(workspace, keep_branch=False)
        record_failure(log)
        raise
    try:
        run = Steering(workspace, packet, settings, agent, session, publisher, console, result, log)
        return steer(run)
    except Exception:
        record_failure(log)
        if not has_work(workspace):
            close_workspace(workspace, keep_branch=False)
            console.show(f"Stopped before any change; removed {workspace.branch} and its worktree.")
            raise
        console.show(
            f"Stopped. Kept for inspection: branch {workspace.branch}, worktree {workspace.path}.\n"
            f"Remove with: git worktree remove --force {workspace.path} && "
            f"git branch -D {workspace.branch}"
        )
        raise


@dataclass
class Steering:
    """What stays fixed while one packet is steered."""

    workspace: Workspace
    packet: WorkPacket
    settings: AgentSettings
    agent: Agent
    session: str
    publisher: Publisher
    console: Console
    result: PacketResult
    log: RunLog | None = None

    @property
    def model(self) -> str:
        return f"{self.settings.provider}/{self.settings.model}"


@dataclass(frozen=True)
class Shown:
    """One attempt as the developer saw it."""

    card: DriftCard
    card_text: str
    needs_reason: bool
    record: RunRecord
    usage: Usage


def show_attempt(run: Steering, number: int, prompt: str, before: Usage | None) -> Shown:
    """Run one attempt, show its card with what it cost, and record it."""
    card, checks, turn = attempt(
        run.workspace, run.packet, run.agent, run.session, prompt, run.result.title, number
    )
    usage = run.agent.usage(run.session)
    input_tokens, output_tokens, cost = spent_since(usage, before)
    spend = Spend(run.model, input_tokens, output_tokens, cost, usage.cost_source)
    card_text = format_card(card, checks, turn.failure, spend)
    run.console.show(card_text)
    run.result.cards.append(card)
    record = RunRecord(
        provider=run.settings.provider,
        model=run.settings.model,
        role=run.packet.role,
        tier=run.packet.tier,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        cost_source=usage.cost_source if cost is not None else None,
    )
    if run.log is not None:
        run.log.attempt(number, record, card)
    needs_reason = card.blocking or not all(check.passed for check in checks)
    return Shown(card, card_text, needs_reason, record, usage)


def ask_decision(run: Steering, number: int, shown: Shown) -> Accept | Redirect | Reject:
    """The developer's decision on a shown attempt, recorded with its outcome."""
    noted = partial(run.log.decision, number) if run.log is not None else unrecorded
    repo = run.workspace.repo
    decision = decide(repo, run.console, shown.needs_reason, run.result.rules, noted)
    reason = decision.reason if isinstance(decision, Accept) else None
    update = {"outcome": OUTCOMES[decision.kind], "accept_reason": reason}
    run.result.records.append(shown.record.model_copy(update=update))
    return decision


def conclude(run: Steering, decision: Accept | Reject, shown: Shown, number: int) -> None:
    """Publish an accepted packet, record the outcome and remove the worktree."""
    if isinstance(decision, Accept):
        usage = shown.usage
        total = Spend(
            run.model, usage.input_tokens, usage.output_tokens, usage.cost_usd, usage.cost_source
        )
        body = pull_request_body(
            run.packet, run.workspace.base_sha, shown.card_text, decision.reason, total, number
        )
        run.result.pull_request = run.publisher.publish(run.workspace, run.result.title, body)
        run.console.show(f"Pull request: {run.result.pull_request}")
    if run.log is not None:
        outcome = "accepted" if isinstance(decision, Accept) else "rejected"
        run.log.finish(outcome, run.result.pull_request)
    close_workspace(run.workspace, keep_branch=isinstance(decision, Accept))


def steer(run: Steering) -> PacketResult:
    """Attempt, show the card, decide; repeat until accepted or rejected."""
    prompt, before = initial_prompt(run.packet), None
    while True:
        number = len(run.result.cards) + 1
        shown = show_attempt(run, number, prompt, before)
        before = shown.usage
        decision = ask_decision(run, number, shown)
        if isinstance(decision, Redirect):
            prompt = redirect_prompt(decision.text, shown.card_text)
            continue
        conclude(run, decision, shown, number)
        return run.result
