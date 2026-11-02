"""Publishing an accepted packet: push its branch and open a pull request."""

import subprocess
from typing import Protocol

from relay.drift.git import run_git
from relay.drift.hygiene import default_branch
from relay.loop.workspace import Workspace


class PublishError(RuntimeError):
    """The branch could not be pushed or the pull request not opened."""


class Publisher(Protocol):
    def publish(self, workspace: Workspace, title: str, body: str) -> str: ...


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
