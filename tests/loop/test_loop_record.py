from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from loop_fixture import (
    SETTINGS,
    FakeAgent,
    FakePublisher,
    ScriptedConsole,
    git,
    packet,
    repo,
)

from relay.cli.main import main
from relay.domain import MakeRule
from relay.loop.record import RunLog, developer_identity, store_path
from relay.loop.steer import PacketResult, run_packet
from relay.loop.workspace import WorkspaceError
from relay.runtime.opencode import OpenCodeError, Usage
from relay.store.runs import Developer, RunStore, StoredRun, StoreError

__all__ = ["repo"]

DRIFTING = {"src/pkg/low/helper.py": "from pkg.high import y\n", "README.md": "changed\n"}
FIXED = {"src/pkg/low/helper.py": "def helper():\n    return 1\n", "README.md": "readme\n"}
BRANCH = "relay/8-add-a-helper-to-low"
DEVELOPER = Developer("Dev", "dev@example.com")
T0 = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)


class Clock:
    """Each reading is ten seconds after the previous one."""

    def __init__(self) -> None:
        self.ticks = 0

    def __call__(self) -> datetime:
        self.ticks += 1
        return T0 + timedelta(seconds=10 * self.ticks)


def logged_run(repo: Path, agent: FakeAgent, console: ScriptedConsole) -> PacketResult:
    log = RunLog(RunStore(store_path(repo)), DEVELOPER, Clock())
    try:
        return run_packet(repo, packet(repo), SETTINGS, agent, FakePublisher(), console, log=log)
    finally:
        log.store.close()


def stored(repo: Path) -> list[StoredRun]:
    store = RunStore(store_path(repo))
    try:
        return store.runs()
    finally:
        store.close()


def test_redirect_rule_and_accept_are_recorded(repo: Path) -> None:
    console = ScriptedConsole("redirect keep low independent", "rule keep helpers small", "accept")

    result = logged_run(repo, FakeAgent(DRIFTING, FIXED), console)

    [run] = stored(repo)
    assert (run.outcome, run.pull_request, run.branch) == ("accepted", result.pull_request, BRANCH)
    assert run.base_sha == result.base_sha and run.developer == DEVELOPER
    first, second = run.attempts
    assert [d.decision.kind for d in first.decisions] == ["redirect"]
    assert [d.decision.kind for d in second.decisions] == ["make_rule", "accept"]
    assert second.decisions[0].decision == MakeRule(spec="keep helpers small")
    assert [a.record for a in run.attempts] == result.records
    assert first.card == result.cards[0] and first.card.blocking
    # clock: start 10s, card shown 20s, redirect 30s; card 40s, rule 50s, accept 60s
    assert (first.steering_seconds, second.steering_seconds, run.steering_seconds) == (10, 20, 30)
    assert run.cost_usd == sum(r.cost_usd or 0 for r in result.records)
    assert first.record.provider == "anthropic" and first.record.cost_source == "runtime"


def test_reject_is_recorded(repo: Path) -> None:
    logged_run(repo, FakeAgent(DRIFTING), ScriptedConsole("reject"))

    [run] = stored(repo)
    assert (run.outcome, run.attempt_count, run.pull_request) == ("rejected", 1, None)


class CrashingConsole(ScriptedConsole):
    """The process dies at the decision prompt."""

    def answer(self, question: str) -> str:
        raise KeyboardInterrupt


def test_a_crash_before_the_decision_is_recovered_by_the_next_run(repo: Path) -> None:
    with pytest.raises(KeyboardInterrupt):
        logged_run(repo, FakeAgent(DRIFTING), CrashingConsole())
    [crashed] = stored(repo)
    assert crashed.outcome is None and crashed.attempts[0].steering_seconds is None
    assert git(repo, "branch", "--list", BRANCH) != ""

    console = ScriptedConsole("y", "accept")
    logged_run(repo, FakeAgent(FIXED), console)

    second, first = stored(repo)
    assert (first.id, first.outcome) == (crashed.id, "failed")
    assert second.outcome == "accepted"
    assert f"Run {crashed.id} on {BRANCH}" in console.text()
    assert f"branch {BRANCH}" in console.text()


def test_a_declined_cleanup_leaves_the_run_pending(repo: Path) -> None:
    with pytest.raises(KeyboardInterrupt):
        logged_run(repo, FakeAgent(DRIFTING), CrashingConsole())

    with pytest.raises(WorkspaceError, match="already exists"):
        logged_run(repo, FakeAgent(FIXED), ScriptedConsole("n"))

    [run] = stored(repo)
    assert run.outcome is None
    assert git(repo, "branch", "--list", BRANCH) != ""


class FailingAgent(FakeAgent):
    def usage(self, session: str) -> Usage:
        raise OpenCodeError("server went away")


def test_an_error_mid_run_is_recorded_as_failed(repo: Path) -> None:
    with pytest.raises(OpenCodeError):
        logged_run(repo, FailingAgent(DRIFTING), ScriptedConsole())

    [run] = stored(repo)
    assert (run.outcome, run.attempt_count) == ("failed", 0)


def test_all_worktrees_share_one_store(repo: Path, tmp_path: Path) -> None:
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "-q", "-b", "other", str(linked))

    assert (linked / ".git").is_file()
    assert store_path(linked) == store_path(repo) == (repo / ".git/relay/runs.sqlite").resolve()


def test_developer_identity_from_git_config(repo: Path) -> None:
    with pytest.raises(StoreError, match="user.email"):
        developer_identity(repo)

    git(repo, "config", "user.email", "dev@example.com")
    assert developer_identity(repo) == Developer("dev@example.com", "dev@example.com")
    git(repo, "config", "user.name", "Dev")
    assert developer_identity(repo) == DEVELOPER


def test_relay_runs_lists_runs_and_totals(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["runs", "--repo", str(repo)]) == 0
    assert capsys.readouterr().out.startswith("No runs recorded yet.\nRun store: ")
    logged_run(repo, FakeAgent(DRIFTING), ScriptedConsole("reject"))
    logged_run(repo, FakeAgent(DRIFTING, FIXED), ScriptedConsole("redirect smaller", "accept"))

    assert main(["runs", "--repo", str(repo), "--limit", "1"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[1].split() == [
        "2",
        "#8",
        "accepted",
        "2",
        "$0.0200",
        "0m20s",
        "anthropic/claude-sonnet-5-5",
    ]
    assert len(lines) == 5
    assert lines[3] == (
        "All 2 runs: 1 accepted, total cost $0.0300; per accepted run: $0.0300 and 0m30s steering"
    )
    assert lines[4] == f"Run store: {store_path(repo)}"
