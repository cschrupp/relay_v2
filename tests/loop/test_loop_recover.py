from pathlib import Path

import pytest
from loop_fixture import SETTINGS, FakeAgent, FakePublisher, ScriptedConsole, git, packet, repo

from relay.loop.publish import PublishError, PullRequestLookup, branch_pull_request
from relay.loop.record import RunLog, store_path
from relay.loop.steer import run_packet
from relay.loop.workspace import Workspace, worktree_path
from relay.store.runs import Developer, RunStore, StoredRun

__all__ = ["repo"]

PASSING = {"src/pkg/low/helper.py": "def helper():\n    return 1\n"}
BRANCH = "relay/8-add-a-helper-to-low"
URL = "https://github.test/pr/7"


class CrashingPublisher(FakePublisher):
    """The pull request is opened, then the process dies before the outcome is saved."""

    def publish(self, workspace: Workspace, title: str, body: str) -> str:
        super().publish(workspace, title, body)
        raise KeyboardInterrupt


def logged_run(
    repo: Path,
    console: ScriptedConsole,
    publisher: FakePublisher | None = None,
    find: PullRequestLookup = branch_pull_request,
    **changes: object,
) -> None:
    log = RunLog(RunStore(store_path(repo)), Developer("Dev", "dev@example.com"))
    work = packet(repo, **changes)
    agent, publisher = FakeAgent(PASSING), publisher or FakePublisher()
    try:
        run_packet(repo, work, SETTINGS, agent, publisher, console, None, log, None, find)
    finally:
        log.store.close()


def stored(repo: Path) -> dict[str, StoredRun]:
    store = RunStore(store_path(repo))
    try:
        return {run.branch: run for run in store.runs()}
    finally:
        store.close()


def crash_after_publishing(repo: Path) -> None:
    with pytest.raises(KeyboardInterrupt):
        logged_run(repo, ScriptedConsole("accept"), CrashingPublisher())


def test_a_crash_after_the_pr_opened_is_recovered_as_accepted(repo: Path) -> None:
    crash_after_publishing(repo)
    assert stored(repo)[BRANCH].outcome is None

    console = ScriptedConsole("y", "reject")
    logged_run(repo, console, find=lambda _, branch: URL if branch == BRANCH else None, issue=9)

    recovered = stored(repo)[BRANCH]
    assert (recovered.outcome, recovered.pull_request) == ("accepted", URL)
    assert f"It opened {URL}" in console.questions[0]
    assert git(repo, "branch", "--list", BRANCH) != ""
    assert not worktree_path(repo, BRANCH).exists()


def test_gh_unavailable_leaves_the_run_pending(repo: Path) -> None:
    crash_after_publishing(repo)

    def unavailable(_: Path, __: str) -> str | None:
        raise PublishError("cannot run gh: not found")

    console = ScriptedConsole("reject")
    logged_run(repo, console, find=unavailable, issue=9)

    assert stored(repo)[BRANCH].outcome is None
    assert "Cannot tell whether it opened a pull request (cannot run gh: not found)" in (
        console.text()
    )
    assert git(repo, "branch", "--list", BRANCH) != ""


def test_an_accepted_run_without_a_pr_is_offered_as_failed(repo: Path) -> None:
    crash_after_publishing(repo)

    console = ScriptedConsole("y", "reject")
    logged_run(repo, console, find=lambda _, __: None, issue=9)

    assert stored(repo)[BRANCH].outcome == "failed"
    assert "record it as failed" in console.questions[0]
    assert git(repo, "branch", "--list", BRANCH) == ""


def test_branch_pull_request_fails_loudly_without_gh(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(repo))

    with pytest.raises(PublishError, match="cannot run gh"):
        branch_pull_request(repo, BRANCH)
