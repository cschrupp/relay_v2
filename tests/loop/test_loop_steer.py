from pathlib import Path

import pytest
from loop_fixture import (
    IMPORTLINTER,
    SETTINGS,
    FakeAgent,
    FakePublisher,
    ScriptedConsole,
    git,
    packet,
    repo,
)

from relay.domain import Accept, MakeRule, Redirect, Reject, parse_rules
from relay.loop.steer import PacketResult, parse_decision, run_packet
from relay.loop.workspace import WorkspaceError
from relay.runtime.opencode import OpenCodeError, SessionSpec, Usage

__all__ = ["repo"]

DRIFTING = {"src/pkg/low/helper.py": "from pkg.high import y\n", "README.md": "changed\n"}
FIXED = {"src/pkg/low/helper.py": "def helper():\n    return 1\n", "README.md": "readme\n"}
BRANCH = "relay/8-add-a-helper-to-low"


def run(
    repo: Path, agent: FakeAgent, console: ScriptedConsole, **changes: object
) -> tuple[PacketResult, FakePublisher]:
    publisher = FakePublisher()
    result = run_packet(repo, packet(repo, **changes), SETTINGS, agent, publisher, console)
    return result, publisher


def worktrees(repo: Path) -> int:
    return git(repo, "worktree", "list").count("\n") + 1


def test_drift_redirect_then_accept_opens_a_pull_request(repo: Path) -> None:
    agent = FakeAgent(DRIFTING, FIXED)
    console = ScriptedConsole("redirect keep low independent of high", "accept")

    result, publisher = run(repo, agent, console)

    first_card, second_card = result.cards
    assert first_card.blocking
    assert {f.kind for f in first_card.findings} == {
        "new_cycle",
        "layer_violation",
        "outside_scope",
    }
    assert second_card.findings == ()
    assert "BLOCKING layer_violation: pkg.low imports pkg.high" in console.text()
    assert "keep low independent of high" in agent.prompts[1]
    assert "layer_violation" in agent.prompts[1]
    assert len(result.base_sha) == 40 and first_card.base_sha == result.base_sha
    [(branch, title, body)] = publisher.published
    assert (branch, title) == (BRANCH, "Add a helper to low")
    assert "Closes #8" in body and result.base_sha in body
    assert result.pull_request == "https://github.test/pr/1"
    assert [r.outcome for r in result.records] == ["redirected", "accepted"]
    assert [(r.input_tokens, r.output_tokens, str(r.cost_usd)) for r in result.records] == [
        (1000, 100, "0.01"),
        (1000, 100, "0.01"),
    ]
    assert git(repo, "rev-list", "--count", f"{result.base_sha}..{BRANCH}") == "2"
    assert worktrees(repo) == 1


def test_blocking_card_needs_a_reason_to_accept(repo: Path) -> None:
    console = ScriptedConsole("accept", "accept approved layer exception, see #7")

    result, publisher = run(repo, FakeAgent(DRIFTING), console)

    assert any("accept <reason>" in line for line in console.shown)
    assert result.records[-1].accept_reason == "approved layer exception, see #7"
    assert "approved layer exception, see #7" in publisher.published[0][2]


def test_failed_acceptance_command_needs_a_reason(repo: Path) -> None:
    console = ScriptedConsole("accept", "accept known failure")

    result, _ = run(repo, FakeAgent({}), console, acceptance_commands=("echo broken; exit 3",))

    assert "FAIL     echo broken; exit 3" in console.text()
    assert "broken" in console.text()
    assert result.records[-1].accept_reason == "known failure"


def test_tests_and_rules_are_read_only_and_deleting_them_is_blocking(repo: Path) -> None:
    agent = FakeAgent(
        {
            "tests/test_low.py": "def test_low():\n    assert True\n",
            ".importlinter": "",
            "src/pkg/x.py": "y = 1\n",
        }
    )
    second = FakeAgent({"tests/test_low.py": None})

    run(repo, agent, ScriptedConsole("reject"))
    result, _ = run(repo, second, ScriptedConsole("reject"))

    assert agent.blocked_writes == ["tests/test_low.py", ".importlinter"]
    kinds = {(f.kind, f.severity) for f in result.cards[0].findings}
    assert ("edited_test", "blocking") in kinds


def test_reject_removes_worktree_and_branch(repo: Path) -> None:
    result, publisher = run(repo, FakeAgent(DRIFTING), ScriptedConsole("reject"))

    assert result.records[-1].outcome == "rejected"
    assert publisher.published == []
    assert worktrees(repo) == 1
    assert git(repo, "branch", "--list", BRANCH) == ""


def test_rules_are_written_and_import_rules_need_confirmation(repo: Path) -> None:
    console = ScriptedConsole(
        "rule pkg.low must not import pkg.high", "y", "rule keep helpers small", "reject"
    )

    result, _ = run(repo, FakeAgent({}), console)

    rules = parse_rules((repo / ".relay/rules.yaml").read_text())
    assert [note.text for note in rules.rules] == [
        "pkg.low must not import pkg.high",
        "keep helpers small",
    ]
    assert result.rules == ["pkg.low must not import pkg.high", "keep helpers small"]
    contract = (repo / ".importlinter").read_text().removeprefix(IMPORTLINTER)
    assert "name = pkg.low must not import pkg.high" in contract
    assert "layers =\n    pkg.high\n    pkg.low\n" in contract
    assert len(console.questions) == 4


def test_declined_import_contract_leaves_importlinter_alone(repo: Path) -> None:
    run(
        repo, FakeAgent({}), ScriptedConsole("rule pkg.low must not import pkg.high", "n", "reject")
    )

    assert (repo / ".importlinter").read_text() == IMPORTLINTER
    assert (repo / ".relay/rules.yaml").exists()


def test_a_packet_gets_exactly_one_branch(repo: Path) -> None:
    git(repo, "branch", BRANCH)

    with pytest.raises(WorkspaceError, match="already exists"):
        run(repo, FakeAgent({}), ScriptedConsole())

    assert worktrees(repo) == 1


def test_packet_without_issue_is_refused(repo: Path) -> None:
    with pytest.raises(WorkspaceError, match="issue number"):
        run(repo, FakeAgent({}), ScriptedConsole(), issue=None)


@pytest.mark.parametrize(
    ("line", "decision"),
    [
        ("accept", Accept()),
        ('accept "approved, see #7"', Accept(reason="approved, see #7")),
        ("redirect   smaller please ", Redirect(text="smaller please")),
        ("rule a must not import b", MakeRule(spec="a must not import b")),
        ("reject", Reject()),
        ("redirect", None),
        ("rule", None),
        ("reject now", None),
        ("ship it", None),
    ],
)
def test_parse_decision(line: str, decision: object) -> None:
    assert parse_decision(line) == decision


class BrokenAgent(FakeAgent):
    def __init__(self, fail_on: str) -> None:
        super().__init__({"src/pkg/low/helper.py": "y = 1\n"})
        self.fail_on = fail_on

    def start(self, spec: SessionSpec) -> str:
        if self.fail_on == "start":
            raise OpenCodeError("connection refused")
        return super().start(spec)

    def usage(self, session: str) -> Usage:
        raise OpenCodeError("server went away")


def test_agent_that_cannot_start_leaves_nothing_behind(repo: Path) -> None:
    with pytest.raises(OpenCodeError):
        run(repo, BrokenAgent("start"), ScriptedConsole())

    assert worktrees(repo) == 1
    assert git(repo, "branch", "--list", BRANCH) == ""


def test_failure_mid_run_keeps_the_work_and_says_where(repo: Path) -> None:
    console = ScriptedConsole("reject")

    with pytest.raises(OpenCodeError, match="went away"):
        run(repo, BrokenAgent("usage"), console)

    assert worktrees(repo) == 2
    assert git(repo, "branch", "--list", BRANCH) != ""
    assert f"Kept for inspection: branch {BRANCH}" in console.text()
