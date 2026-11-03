"""Recording `relay run` in the run store, and recovering runs a crash left pending.

There is one store per repository, in git's common directory, so every worktree of the
repository writes to the same file. The loop records as it goes: the run when its
branch exists, each attempt when its card is shown, each decision when it is made, and
the outcome when the packet ends. A run the process never finished (a crash, Ctrl-C)
stays pending, and the next `relay run` offers to clean up what it left.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from relay.domain import Accept, DriftCard, MakeRule, RunRecord, SteerDecision, WorkPacket
from relay.drift.git import GitError, run_git
from relay.loop.publish import PublishError, PullRequestLookup, branch_pull_request
from relay.loop.workspace import discard_packet, git_common_dir
from relay.store.runs import DecidedBy, Developer, RunOutcome, RunStore, StoredRun, StoreError

STORE_FILE = "relay/runs.sqlite"


def store_path(repo: Path) -> Path:
    return git_common_dir(repo) / STORE_FILE


def now() -> datetime:
    return datetime.now(UTC)


def developer_identity(repo: Path) -> Developer:
    """The developer as git knows them in this repository."""

    def config(key: str) -> str:
        try:
            return run_git(repo, "config", "--get", key).decode().strip()
        except GitError:
            return ""

    name, email = config("user.name"), config("user.email")
    if not email:
        raise StoreError("git config user.email is not set; Relay records who steered each run")
    return Developer(name or email, email)


@dataclass
class RunLog:
    """One run's records; every method writes immediately in its own transaction."""

    store: RunStore
    developer: Developer
    clock: Callable[[], datetime] = now
    run_id: int | None = None

    def current(self) -> int:
        if self.run_id is None:
            raise StoreError("no run has been started")
        return self.run_id

    def start(self, packet: WorkPacket, branch: str) -> None:
        self.run_id = self.store.start_run(packet, branch, self.developer, self.clock())

    def attempt(self, number: int, record: RunRecord, card: DriftCard) -> None:
        self.store.record_attempt(self.current(), number, record, card, self.clock())

    def decision(self, number: int, decision: SteerDecision, by: DecidedBy = "developer") -> None:
        self.store.record_decision(self.current(), number, decision, self.clock(), by)

    def finish(self, outcome: RunOutcome, pull_request: str | None = None) -> None:
        self.store.finish_run(self.current(), outcome, self.clock(), pull_request)


def accepted_last(run: StoredRun) -> bool:
    """Whether the run's last decision was the developer's accept (its PR may exist)."""
    if not run.attempts:
        return False
    final = [d for d in run.attempts[-1].decisions if not isinstance(d.decision, MakeRule)]
    return bool(final) and isinstance(final[-1].decision, Accept)


def recover_pending(
    repo: Path,
    log: RunLog,
    confirm: Callable[[str], bool],
    show: Callable[[str], None],
    find_pull_request: PullRequestLookup = branch_pull_request,
) -> None:
    """Offer to close each run a crash left pending, and clean up what it left.

    A run that crashed after its pull request was opened is closed as accepted with the
    PR's link, keeping the branch; any other as failed. A pending run may also be one
    still running in another terminal, so nothing is removed or closed without the
    developer's yes. When `gh` cannot say whether a PR exists, the run stays pending.
    """
    for run in log.store.pending_runs():
        decided = sum(1 for a in run.attempts if a.steering_seconds is not None)
        show(
            f"Run {run.id} on {run.branch} (started {run.started_at:%Y-%m-%d %H:%M} UTC) never "
            f"finished: {len(run.attempts)} attempt(s), {decided} decided. It crashed, or it "
            "is still running in another terminal."
        )
        url = None
        if accepted_last(run):
            try:
                url = find_pull_request(repo, run.branch)
            except PublishError as error:
                show(f"Cannot tell whether it opened a pull request ({error}); it stays pending.")
                continue
        if url is not None:
            close_published(repo, log, run, url, confirm, show)
        elif confirm("Remove its worktree and branch, and record it as failed? [y/N] "):
            removed = discard_packet(repo, run.branch)
            log.store.finish_run(run.id, "failed", log.clock())
            show(f"Removed {', '.join(removed) or 'nothing (already gone)'}; run {run.id} failed.")


def close_published(
    repo: Path,
    log: RunLog,
    run: StoredRun,
    url: str,
    confirm: Callable[[str], bool],
    show: Callable[[str], None],
) -> None:
    """Close a run whose pull request exists as accepted; its branch stays for the PR."""
    question = f"It opened {url}. Record it as accepted and remove its worktree? [y/N] "
    if not confirm(question):
        return
    removed = discard_packet(repo, run.branch, keep_branch=True)
    log.store.finish_run(run.id, "accepted", log.clock(), url)
    kept = f"kept branch {run.branch}"
    show(f"Removed {', '.join(removed) or 'nothing'}, {kept}; run {run.id} accepted ({url}).")
