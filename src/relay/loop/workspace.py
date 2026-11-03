"""One branch and one git worktree per work packet.

The branch is `relay/<issue>-<slug>`; the worktree lives under the repository's git
directory (`relay-worktrees/`), so it never shows up in the developer's `git status`.
Redirects and retries commit to the same branch. A packet that already has a branch is
refused rather than reused: finish it, or remove it with `relay tidy`.
"""

import re
import stat
from dataclasses import dataclass
from pathlib import Path

from relay.domain import WorkPacket
from relay.drift.card import is_rule_path
from relay.drift.git import GitError, resolve_commit, run_git
from relay.drift.report import is_test_path

SLUG_LENGTH = 30
WORKTREE_DIRECTORY = "relay-worktrees"
WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


class WorkspaceError(RuntimeError):
    """The packet cannot get its branch and worktree."""


@dataclass(frozen=True)
class Workspace:
    repo: Path
    path: Path
    branch: str
    base_sha: str


def slug(text: str) -> str:
    """Lowercase words joined by `-`, at most SLUG_LENGTH long, cut at a word boundary."""
    words = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(words) <= SLUG_LENGTH:
        return words or "packet"
    cut = words[: SLUG_LENGTH + 1].rfind("-")
    return words[:cut] if cut > 0 else words[:SLUG_LENGTH]


def branch_name(packet: WorkPacket) -> str:
    if packet.issue is None:
        raise WorkspaceError("relay run needs the packet's issue number (`issue:` in the packet)")
    return f"relay/{packet.issue}-{slug(packet.goal)}"


def git_common_dir(repo: Path) -> Path:
    """The directory all of the repository's worktrees share (`.git` of the main one)."""
    common = Path(run_git(repo, "rev-parse", "--git-common-dir").decode().strip())
    return (repo / common).resolve()


def worktree_path(repo: Path, branch: str) -> Path:
    return git_common_dir(repo) / WORKTREE_DIRECTORY / branch.replace("/", "-")


def open_workspace(repo: Path, packet: WorkPacket) -> Workspace:
    """Resolve the base to its full SHA, then create the packet's branch and worktree."""
    base = resolve_commit(repo, packet.base_sha)
    branch = branch_name(packet)
    try:
        run_git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")
    except GitError:
        pass
    else:
        raise WorkspaceError(f"branch {branch} already exists; finish it or remove it first")
    path = worktree_path(repo, branch)
    run_git(repo, "worktree", "add", "-q", "-b", branch, str(path), base)
    return Workspace(repo, path, branch, base)


def commit_attempt(workspace: Workspace, message: str) -> str:
    """Commit everything the agent changed and return the branch head."""
    run_git(workspace.path, "add", "-A")
    staged = run_git(workspace.path, "diff", "--cached", "--name-only").strip()
    if staged:
        run_git(workspace.path, "commit", "-q", "--no-verify", "-m", message)
    return run_git(workspace.path, "rev-parse", "HEAD").decode().strip()


def protect(workspace: Workspace) -> list[Path]:
    """Make tracked test and rule files read-only for the agent's turn; return them."""
    tracked = run_git(workspace.path, "ls-files", "-z").decode().split("\0")
    protected = [
        workspace.path / path
        for path in tracked
        if path and (is_test_path(path) or is_rule_path(path))
    ]
    for path in protected:
        if path.is_file():
            path.chmod(path.stat().st_mode & ~WRITE_BITS)
    return protected


def unprotect(paths: list[Path]) -> None:
    for path in paths:
        if path.is_file():
            path.chmod(path.stat().st_mode | stat.S_IWUSR)


def has_work(workspace: Workspace) -> bool:
    """Whether the packet branch holds anything: a commit past the base, or changed files."""
    head = run_git(workspace.path, "rev-parse", "HEAD").decode().strip()
    changed = run_git(workspace.path, "status", "--porcelain").strip()
    return head != workspace.base_sha or bool(changed)


def close_workspace(workspace: Workspace, keep_branch: bool) -> None:
    """Remove the worktree; delete the branch too unless it is kept for a pull request."""
    run_git(workspace.repo, "worktree", "remove", "--force", str(workspace.path))
    if not keep_branch:
        run_git(workspace.repo, "branch", "-q", "-D", workspace.branch)


def discard_packet(repo: Path, branch: str, keep_branch: bool = False) -> list[str]:
    """Remove whatever is left of a packet's worktree and branch; return what was removed."""
    removed: list[str] = []
    path = worktree_path(repo, branch)
    if path.exists():
        run_git(repo, "worktree", "remove", "--force", str(path))
        removed.append(f"worktree {path}")
    run_git(repo, "worktree", "prune")
    if keep_branch:
        return removed
    try:
        run_git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")
    except GitError:
        return removed
    run_git(repo, "branch", "-q", "-D", branch)
    return [*removed, f"branch {branch}"]
