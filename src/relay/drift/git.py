"""Read a repository at a given commit without checking it out."""

import subprocess
from collections.abc import Sequence
from pathlib import Path


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


def list_files(repo: Path, sha: str) -> list[str]:
    """Return every file path in the tree of sha."""
    output = run_git(repo, "ls-tree", "-r", "-z", "--name-only", sha)
    return [path.decode("utf-8") for path in output.split(b"\0") if path]


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
