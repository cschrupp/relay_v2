"""Read a repository at a given commit without checking it out."""

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

SYMLINK_MODE = b"120000"


class GitError(RuntimeError):
    """A git command failed or returned something unexpected."""


def run_git(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    """Run one git command in repo and return its stdout, raising GitError on failure."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=stdin,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(f"git {args[0]} failed in {repo}: {message}")
    return result.stdout


def resolve_commit(repo: Path, rev: str) -> str:
    """Return the full SHA of the commit that rev names."""
    return run_git(repo, "rev-parse", "--verify", f"{rev}^{{commit}}").decode().strip()


def commit_date(repo: Path, sha: str) -> str:
    """Return the committer date of sha in strict ISO 8601."""
    return run_git(repo, "show", "-s", "--format=%cI", sha).decode().strip()


@dataclass(frozen=True)
class Commit:
    sha: str
    date: str
    subject: str


@dataclass(frozen=True)
class TreeListing:
    files: list[str]
    symlinks: list[str]


def list_files(repo: Path, sha: str) -> TreeListing:
    """Return the regular file paths in the tree of sha, with symlinks listed apart."""
    output = run_git(repo, "ls-tree", "-r", "-z", sha)
    files: list[str] = []
    symlinks: list[str] = []
    for entry in filter(None, output.split(b"\0")):
        meta, _, path = entry.partition(b"\t")
        mode, kind, _ = meta.split(b" ")
        if kind != b"blob":
            continue
        (symlinks if mode == SYMLINK_MODE else files).append(path.decode("utf-8"))
    return TreeListing(files, symlinks)


def first_parent_commits(repo: Path, rev: str) -> list[Commit]:
    """Return the first-parent history of rev, oldest first."""
    output = run_git(repo, "log", "--first-parent", "--reverse", "--format=%H%x1f%cI%x1f%s", rev)
    commits: list[Commit] = []
    for line in output.decode("utf-8", errors="replace").splitlines():
        sha, date, subject = line.split("\x1f", 2)
        commits.append(Commit(sha, date, subject))
    return commits


def read_files(repo: Path, sha: str, paths: Sequence[str]) -> dict[str, str]:
    """Return the text of each path at sha, read in one `git cat-file --batch` call."""
    if not paths:
        return {}
    request = "".join(f"{sha}:{path}\n" for path in paths).encode("utf-8")
    output = run_git(repo, "cat-file", "--batch", stdin=request)
    texts: dict[str, str] = {}
    position = 0
    for path in paths:
        header_end = output.index(b"\n", position)
        header = output[position:header_end].split()
        if len(header) != 3 or header[1] != b"blob":
            raise GitError(f"{sha}:{path} is not a readable file")
        start = header_end + 1
        end = start + int(header[2])
        texts[path] = output[start:end].decode("utf-8", errors="replace")
        position = end + 1
    return texts


@dataclass(frozen=True)
class Change:
    """One file changed between two commits; line counts are None for binary files."""

    status: str
    path: str
    added: int | None
    deleted: int | None


def diff_changes(repo: Path, base: str, result: str) -> list[Change]:
    """Return every file changed from base to result, renames shown as delete plus add."""
    names = run_git(repo, "diff", "-z", "--no-renames", "--name-status", base, result)
    fields = names.decode("utf-8").split("\0")
    statuses = dict(zip(fields[1::2], fields[0::2], strict=False))
    numstat = run_git(repo, "diff", "-z", "--no-renames", "--numstat", base, result)
    changes: list[Change] = []
    for entry in filter(None, numstat.decode("utf-8").split("\0")):
        added, deleted, path = entry.split("\t", 2)
        changes.append(
            Change(
                status=statuses.get(path, "M")[:1],
                path=path,
                added=None if added == "-" else int(added),
                deleted=None if deleted == "-" else int(deleted),
            )
        )
    return changes


def read_optional(repo: Path, sha: str, path: str) -> str | None:
    """Return the text of path at sha, or None when the commit has no such regular file."""
    if path not in list_files(repo, sha).files:
        return None
    return read_files(repo, sha, [path])[path]
