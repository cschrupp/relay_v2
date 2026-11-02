"""Plan and apply branch clean-up. Planning is read-only; deleting needs `apply_plan`.

A ref can go when its branch is merged (contained in the default branch, or its pull
request was merged), or when its PR state is known, it has no open PR and its last
commit is older than the stale limit. Never touched: the default branch, any branch
with an open PR, and any branch checked out in a worktree.

Before a ref that is not contained in the default branch is deleted, its tip is tagged
`archive/<name>` (or `archive/<name>-<sha7>` if that tag already points elsewhere) and
the tag is pushed to the ref's remote, or to `origin` for a local branch when one exists.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from relay.drift.git import GitError, run_git
from relay.drift.hygiene import (
    DEFAULT_STALE_DAYS,
    PullRequest,
    branch_refs,
    default_branch,
    stale_names,
    worktrees,
)


@dataclass(frozen=True)
class TidyAction:
    ref: str
    name: str
    remote: str | None
    sha: str
    reason: str
    archive: bool


def deletion_reason(
    name: str, contained: bool, prs: list[PullRequest] | None, stale: set[str], days: int
) -> str | None:
    """Why a branch can be deleted, or None when it must stay."""
    if contained:
        return "merged into the default branch"
    merged = [pr for pr in prs or [] if pr.head == name and pr.state == "MERGED"]
    if merged:
        return f"PR #{merged[0].number} merged"
    if prs is not None and name in stale:
        return f"no open PR and no commits in {days} days"
    return None


def plan_tidy(
    repo: Path, prs: list[PullRequest] | None, now: datetime, days: int = DEFAULT_STALE_DAYS
) -> list[TidyAction]:
    """List every branch ref that can be deleted, with the reason."""
    default_name, default_ref = default_branch(repo)
    refs = branch_refs(repo, default_ref)
    protected = {default_name} | {pr.head for pr in prs or [] if pr.state == "OPEN"}
    current = run_git(repo, "branch", "--show-current").decode().strip()
    protected |= {tree.branch for tree in worktrees(repo) if tree.branch} | {current}
    stale = stale_names(refs, now, days)
    actions: list[TidyAction] = []
    for ref in refs:
        if ref.name in protected:
            continue
        reason = deletion_reason(ref.name, ref.contained, prs, stale, days)
        if reason is not None:
            actions.append(
                TidyAction(ref.ref, ref.name, ref.remote, ref.sha, reason, not ref.contained)
            )
    return actions


def archive_tag(repo: Path, action: TidyAction) -> str:
    """Create (or reuse) the archive tag for an action's tip and return its name."""
    for tag in (f"archive/{action.name}", f"archive/{action.name}-{action.sha[:7]}"):
        try:
            existing = run_git(repo, "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}")
        except GitError:
            run_git(repo, "tag", tag, action.sha)
            return tag
        if existing.decode().strip() == action.sha:
            return tag
    raise GitError(f"cannot create an archive tag for {action.name}")


def apply_action(repo: Path, action: TidyAction) -> str:
    """Archive if needed, then delete one ref; return what was done."""
    remotes = run_git(repo, "remote").decode().split()
    push_to = action.remote or ("origin" if "origin" in remotes else None)
    done = ""
    if action.archive:
        tag = archive_tag(repo, action)
        if push_to is not None:
            run_git(repo, "push", "-q", push_to, f"refs/tags/{tag}")
        done = f"tagged {tag}{' and pushed it' if push_to else ' (no remote to push to)'}; "
    if action.remote is None:
        run_git(repo, "branch", "-D", action.name)
    else:
        run_git(repo, "push", "-q", action.remote, "--delete", action.name)
    return f"{done}deleted {action.ref}"
