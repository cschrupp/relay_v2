"""Branch hygiene: branch sprawl is drift in the repository's structure.

Branches are counted by name, local and remote together, leaving out the default
branch. A name is *merged* when one of its refs is contained in the default branch or
its pull request was merged (which also catches squash merges). Pull request state
comes from `gh`; when `gh` is missing, fails, or the repository has no remote, every
PR-dependent answer is None (unknown) rather than guessed.
"""

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from relay.domain import DriftFinding, Rules
from relay.drift.git import GitError, run_git

DEFAULT_STALE_DAYS = 14
GH_TIMEOUT_SECONDS = 60
GH_LIMIT = "2000"


@dataclass(frozen=True)
class PullRequest:
    number: int
    head: str
    state: str


@dataclass(frozen=True)
class BranchRef:
    ref: str
    name: str
    remote: str | None
    sha: str
    date: str
    contained: bool


@dataclass(frozen=True)
class Worktree:
    path: str
    branch: str | None
    prunable: bool


@dataclass(frozen=True)
class Hygiene:
    default_branch: str
    local_branches: int
    remote_branches: int
    branches: int
    merged: tuple[str, ...]
    without_open_pr: tuple[str, ...] | None
    stale: tuple[str, ...]
    stale_days: int
    worktrees: tuple[Worktree, ...]
    open_pull_requests: int | None
    budget: int | None
    findings: tuple[DriftFinding, ...]


def default_branch(repo: Path) -> tuple[str, str]:
    """Return (name, ref) of the default branch: origin's HEAD, else main, else master."""
    try:
        ref = run_git(repo, "symbolic-ref", "-q", "refs/remotes/origin/HEAD").decode().strip()
        return ref.removeprefix("refs/remotes/origin/"), ref
    except GitError:
        pass
    for name in ("main", "master"):
        try:
            run_git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{name}")
            return name, f"refs/heads/{name}"
        except GitError:
            continue
    name = run_git(repo, "symbolic-ref", "--short", "HEAD").decode().strip()
    return name, f"refs/heads/{name}"


def branch_refs(repo: Path, default_ref: str) -> list[BranchRef]:
    """Every local and remote branch ref, except remote HEAD pointers."""
    contained = set(
        run_git(repo, "for-each-ref", f"--merged={default_ref}", "--format=%(refname)")
        .decode()
        .split()
    )
    output = run_git(
        repo,
        "for-each-ref",
        "--format=%(refname)%00%(objectname)%00%(committerdate:iso-strict)",
        "refs/heads",
        "refs/remotes",
    ).decode()
    refs: list[BranchRef] = []
    for line in output.splitlines():
        ref, sha, date = line.split("\0")
        if ref.startswith("refs/heads/"):
            name, remote = ref.removeprefix("refs/heads/"), None
        else:
            remote, _, name = ref.removeprefix("refs/remotes/").partition("/")
            if name == "HEAD":
                continue
        refs.append(BranchRef(ref, name, remote, sha, date, ref in contained))
    return refs


def pull_requests(repo: Path) -> list[PullRequest] | None:
    """All pull requests of the repository's GitHub remote via `gh`, or None if unknown."""
    if not run_git(repo, "remote").strip():
        return None
    command = ["gh", "pr", "list", "--state", "all", "--limit", GH_LIMIT]
    command += ["--json", "number,headRefName,state"]
    try:
        result = subprocess.run(
            command, cwd=repo, capture_output=True, text=True, timeout=GH_TIMEOUT_SECONDS
        )
        if result.returncode != 0:
            return None
        rows: list[dict[str, object]] = json.loads(result.stdout)
        return [
            PullRequest(int(str(r["number"])), str(r["headRefName"]), str(r["state"])) for r in rows
        ]
    except OSError, subprocess.TimeoutExpired, ValueError, KeyError:
        return None


def worktrees(repo: Path) -> list[Worktree]:
    """Worktrees other than the main one, from `git worktree list --porcelain`."""
    blocks = run_git(repo, "worktree", "list", "--porcelain").decode().strip().split("\n\n")
    found: list[Worktree] = []
    for block in blocks[1:]:
        fields: dict[str, str] = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            fields[key] = value
        branch = fields.get("branch")
        found.append(
            Worktree(
                path=fields.get("worktree", ""),
                branch=branch.removeprefix("refs/heads/") if branch else None,
                prunable="prunable" in fields,
            )
        )
    return found


def merged_names(refs: list[BranchRef], prs: list[PullRequest] | None) -> set[str]:
    merged = {ref.name for ref in refs if ref.contained}
    return merged | {pr.head for pr in prs or [] if pr.state == "MERGED"}


def stale_names(refs: list[BranchRef], now: datetime, days: int) -> set[str]:
    newest: dict[str, datetime] = {}
    for ref in refs:
        date = datetime.fromisoformat(ref.date)
        newest[ref.name] = max(date, newest.get(ref.name, date))
    cutoff = now - timedelta(days=days)
    return {name for name, date in newest.items() if date < cutoff}


def build_hygiene(
    repo: Path,
    rules: Rules,
    prs: list[PullRequest] | None,
    now: datetime,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> Hygiene:
    """Measure branch sprawl and check it against the branch budget."""
    default_name, default_ref = default_branch(repo)
    refs = [ref for ref in branch_refs(repo, default_ref) if ref.name != default_name]
    names = {ref.name for ref in refs}
    open_heads = {pr.head for pr in prs if pr.state == "OPEN"} if prs is not None else None
    budget = rules.branch_budget(len(open_heads) if open_heads is not None else None)
    findings: list[DriftFinding] = []
    if budget is not None and len(names) > budget:
        message = f"{len(names)} branches besides {default_name}, budget {budget}"
        findings.append(DriftFinding(kind="branch_budget", message=message))
    return Hygiene(
        default_branch=default_name,
        local_branches=sum(ref.remote is None for ref in refs),
        remote_branches=sum(ref.remote is not None for ref in refs),
        branches=len(names),
        merged=tuple(sorted(merged_names(refs, prs) & names)),
        without_open_pr=tuple(sorted(names - open_heads)) if open_heads is not None else None,
        stale=tuple(sorted(stale_names(refs, now, stale_days))),
        stale_days=stale_days,
        worktrees=tuple(worktrees(repo)),
        open_pull_requests=len(open_heads) if open_heads is not None else None,
        budget=budget,
        findings=tuple(findings),
    )
