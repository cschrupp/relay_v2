from collections import Counter
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from loop_fixture import Edits, FakeAgent, FakePublisher, ScriptedConsole, packet, repo

from relay.cli.main import main
from relay.domain import ModelsError, TokenPrice
from relay.loop.agent import OpenCodeAgent, TurnResult
from relay.loop.record import RunLog, store_path
from relay.loop.route import route
from relay.loop.steer import AgentSettings, Cascade, PacketResult, run_packet
from relay.runtime.opencode import SessionEvent, SessionSpec, Usage
from relay.store.runs import Developer, RunStore

__all__ = ["repo"]

PASSING: Edits = {"src/pkg/low/helper.py": "def helper():\n    return 1\n"}
FAILING: Edits = {}  # the acceptance check wants src/pkg/low/helper.py
CHEAP = AgentSettings(
    "implementer",
    "openrouter",
    "cheap-model",
    TokenPrice(input_per_mtok=Decimal(1), output_per_mtok=Decimal(2)),
)
STRONG = AgentSettings("implementer", "anthropic", "strong-model")
ESCALATING = Cascade(STRONG)


class SessionAgent(FakeAgent):
    """A fake agent whose usage is per session, as OpenCode reports it."""

    def __init__(self, *turns: Edits) -> None:
        super().__init__(*turns)
        self.specs: list[SessionSpec] = []
        self.turns_in: Counter[str] = Counter()

    def start(self, spec: SessionSpec) -> str:
        super().start(spec)
        self.specs.append(spec)
        return f"ses_{len(self.specs)}"

    def turn(self, session: str, prompt: str) -> TurnResult:
        self.turns_in[session] += 1
        return super().turn(session, prompt)

    def usage(self, session: str) -> Usage:
        done = self.turns_in[session]
        return Usage(1000 * done, 100 * done, 0, 0, 0, None, None)


def run(
    repo: Path,
    agent: SessionAgent,
    console: ScriptedConsole,
    cascade: Cascade | None = ESCALATING,
    log: RunLog | None = None,
    **changes: object,
) -> tuple[PacketResult, FakePublisher]:
    publisher = FakePublisher()
    work = packet(repo, **changes)
    result = run_packet(repo, work, CHEAP, agent, publisher, console, None, log, cascade)
    return result, publisher


def test_pass_on_cheap_goes_straight_to_the_developer(repo: Path) -> None:
    agent = SessionAgent(PASSING)

    result, _ = run(repo, agent, ScriptedConsole("accept"))

    assert [r.outcome for r in result.records] == ["accepted"]
    assert len(agent.specs) == 1 and agent.specs[0].token_budget == 100000
    assert result.records[0].cost_usd == Decimal("0.0012")
    assert result.records[0].cost_source == "price_table"


def test_pass_on_retry(repo: Path) -> None:
    agent = SessionAgent(FAILING, PASSING)
    console = ScriptedConsole("accept")

    result, _ = run(repo, agent, console)

    assert [(r.outcome, r.tier) for r in result.records] == [
        ("redirected", "cheap"),
        ("accepted", "cheap"),
    ]
    assert "not done: acceptance checks failed" in agent.prompts[1]
    assert "Relay: retry on openrouter/cheap-model: acceptance checks failed" in console.text()
    assert len(console.questions) == 1 and len(agent.specs) == 1


def test_escalation_to_strong_is_recorded_as_relays_decision(repo: Path) -> None:
    agent = SessionAgent(FAILING, FAILING, PASSING)
    log = RunLog(RunStore(store_path(repo)), Developer("Dev", "dev@example.com"))

    result, publisher = run(repo, agent, ScriptedConsole("accept"), log=log)

    assert [(r.tier, r.model) for r in result.records] == [
        ("cheap", "cheap-model"),
        ("cheap", "cheap-model"),
        ("strong", "strong-model"),
    ]
    strong = agent.specs[1]
    assert (strong.provider, strong.model, strong.token_budget) == (
        "anthropic",
        "strong-model",
        100000 - 2200,
    )
    assert "Add a helper to low" in agent.prompts[2] and "cheaper model" in agent.prompts[2]
    assert result.records[2].input_tokens == 1000  # the new session starts from zero
    [stored] = log.store.runs()
    log.store.close()
    decided = [[(d.decision.kind, d.by) for d in a.decisions] for a in stored.attempts]
    assert decided == [[("redirect", "relay")], [("redirect", "relay")], [("accept", "developer")]]
    assert [a.steering_seconds for a in stored.attempts][:2] == [0.0, 0.0]
    assert "openrouter/cheap-model, anthropic/strong-model" in publisher.published[0][2]


def test_after_the_cascade_the_developer_decides(repo: Path) -> None:
    console = ScriptedConsole("reject")

    result, _ = run(repo, SessionAgent(FAILING, FAILING, FAILING), console)

    assert [r.outcome for r in result.records] == ["redirected", "redirected", "rejected"]
    assert len(console.questions) == 1


def test_budget_exhausted_stops_the_cascade_and_redirects(repo: Path) -> None:
    agent = SessionAgent(FAILING, FAILING)
    console = ScriptedConsole("redirect try harder", "reject")

    result, _ = run(repo, agent, console, token_budget=1500)

    assert [r.outcome for r in result.records] == ["redirected", "rejected"]
    assert "Relay: token budget spent (2,200 of 1,500); you decide." in console.text()
    assert "The packet's token budget is spent: accept, rule or reject." in console.text()
    assert len(agent.specs) == 1


def test_warnings_never_trigger_automatic_steps(repo: Path) -> None:
    outside = {**PASSING, "README.md": "changed\n"}

    result, _ = run(repo, SessionAgent(outside), ScriptedConsole("accept"))

    assert result.cards[0].findings and not result.cards[0].blocking
    assert [r.outcome for r in result.records] == ["accepted"]


def test_without_a_cascade_every_card_comes_to_the_developer(repo: Path) -> None:
    console = ScriptedConsole("reject")

    result, _ = run(repo, SessionAgent(FAILING), console, cascade=None)

    assert [r.outcome for r in result.records] == ["rejected"]
    assert "Relay:" not in console.text()


def test_a_strong_packet_retries_but_does_not_escalate(repo: Path) -> None:
    agent = SessionAgent(FAILING, FAILING)

    result, _ = run(repo, agent, ScriptedConsole("reject"), tier="strong")

    assert [r.outcome for r in result.records] == ["redirected", "rejected"]
    assert len(agent.specs) == 1


MODELS = """
implementer:
  cheap:
    provider: openrouter
    model: m1
    family: deepseek
    price: {input_per_mtok: 1, output_per_mtok: 2}
  strong: {provider: anthropic, model: m2, family: claude}
"""


def test_route_reads_the_models_file(repo: Path) -> None:
    with pytest.raises(ModelsError, match="not found"):
        route(repo, "implementer", "cheap", None)
    (repo / ".relay").mkdir()
    (repo / ".relay/models.yaml").write_text(MODELS)

    settings, cascade = route(repo, "implementer", "cheap", None)

    assert (settings.agent, settings.name, settings.price is not None) == (
        "implementer",
        "openrouter/m1",
        True,
    )
    assert cascade.strong is not None and cascade.strong.name == "anthropic/m2"
    assert route(repo, "implementer", "strong", "builder")[0].agent == "builder"
    assert route(repo, "implementer", "strong", None)[1] == Cascade()
    with pytest.raises(ModelsError, match="reviewer"):
        route(repo, "reviewer", "cheap", None)


def step(kind: str) -> SessionEvent:
    return SessionEvent("message.part.updated", {"part": {"type": kind}})


class BudgetClient:
    """Three steps of 1,000 tokens each; the session's totals grow after every step."""

    def __init__(self) -> None:
        self.steps = 0
        self.interrupted = 0

    def check_health(self) -> None:
        return None

    def create_session(self, spec: SessionSpec) -> str:
        return "ses_1"

    def run(self, session: str, prompt: str) -> Iterator[SessionEvent]:
        for _ in range(3):
            if self.interrupted:
                return
            yield step("step-start")
            self.steps += 1
            yield step("step-finish")
        yield SessionEvent("session.idle", {})

    def usage(self, session: str) -> Usage:
        return Usage(800 * self.steps, 150 * self.steps, 50 * self.steps, 0, 0, None, None)

    def interrupt(self, session: str) -> None:
        self.interrupted += 1


def test_agent_interrupts_a_session_over_budget_from_session_totals() -> None:
    client = BudgetClient()
    shown: list[str] = []
    agent = OpenCodeAgent(client, shown.append)  # type: ignore[arg-type]

    session = agent.start(SessionSpec(Path("/w"), "implementer", "p", "m", token_budget=1500))
    turn = agent.turn(session, "do it")

    assert (client.steps, client.interrupted) == (2, 1)
    assert turn.failure == "token budget exceeded: 2,000 of 1,500 tokens; interrupted"
    assert "  token budget exceeded: 2,000 of 1,500 tokens; interrupted" in shown


def test_relay_run_without_model_needs_the_models_file(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    packet_file = Path(__file__).parents[1] / "domain" / "packet.yaml"

    code = main(["run", str(packet_file), "--repo", str(repo), "--no-cascade"])

    assert code == 2
    assert ".relay/models.yaml not found" in capsys.readouterr().out
