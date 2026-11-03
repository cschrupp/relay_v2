"""Publishing an accepted packet: push its branch and open a pull request."""

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from relay.drift.git import run_git
from relay.drift.hygiene import default_branch
from relay.loop.workspace import Workspace


class PublishError(RuntimeError):
    """The branch could not be pushed or the pull request not opened."""


class Publisher(Protocol):
    def publish(self, workspace: Workspace, title: str, body: str) -> str: ...


def branch_pull_request(repo: Path, branch: str) -> str | None:
    """The URL of the branch's pull request in any state, or None when it has none.

    Raises PublishError when `gh` cannot tell, so that no answer is guessed.
    """
    command = ["gh", "pr", "list", "--head", branch, "--state", "all", "--json", "url"]
    command += ["--jq", ".[0].url // empty"]
    try:
        done = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PublishError(f"cannot run gh: {error}") from error
    if done.returncode != 0:
        raise PublishError(f"gh pr list failed: {done.stderr.strip()}")
    return done.stdout.strip() or None


PullRequestLookup = Callable[[Path, str], str | None]


def issue_title(repo: Path, number: int) -> str | None:
    """The GitHub issue's title via `gh`, or None when it cannot be read."""
    command = ["gh", "issue", "view", str(number), "--json", "title", "--jq", ".title"]
    try:
        done = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=30)
    except OSError, subprocess.TimeoutExpired:
        return None
    title = done.stdout.strip()
    return title if done.returncode == 0 and title else None


class GitHubPublisher:
    """Pushes to `origin` and opens the pull request with `gh`."""

    def publish(self, workspace: Workspace, title: str, body: str) -> str:
        run_git(workspace.path, "push", "-q", "-u", "origin", workspace.branch)
        base, _ = default_branch(workspace.repo)
        command = ["gh", "pr", "create", "--base", base, "--head", workspace.branch]
        command += ["--title", title, "--body-file", "-"]
        try:
            done = subprocess.run(
                command, cwd=workspace.path, input=body, capture_output=True, text=True
            )
        except OSError as error:
            raise PublishError(f"cannot run gh: {error}") from error
        if done.returncode != 0:
            raise PublishError(f"gh pr create failed: {done.stderr.strip()}")
        return done.stdout.strip().splitlines()[-1]
