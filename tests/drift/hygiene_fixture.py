import json
import os
import subprocess
from pathlib import Path

import pytest
from conftest import GIT_ENV, FixtureRepo


class RemoteRepo:
    """A fixture repo with a bare `origin` remote, branches and a fake `gh` on PATH."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp_path = tmp_path
        self.repo = FixtureRepo(tmp_path / "repo")
        self.origin = tmp_path / "origin.git"
        self.repo.git("init", "-q", "--bare", "-b", "main", str(self.origin))
        self.base = self.repo.commit({"README.md": "start\n"}, message="start")
        self.repo.git("remote", "add", "origin", str(self.origin))
        self.repo.git("push", "-q", "-u", "origin", "main")
        self.repo.git("remote", "set-head", "origin", "main")
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.prs_file = tmp_path / "prs.json"
        monkeypatch.setenv("PATH", f"{self.bin}{os.pathsep}{os.environ['PATH']}")
        self.set_gh("[]")

    def set_gh(self, output: str, exit_code: int = 0) -> None:
        self.prs_file.write_text(output)
        gh = self.bin / "gh"
        gh.write_text(f'#!/bin/sh\ncat "{self.prs_file}"\nexit {exit_code}\n')
        gh.chmod(0o755)

    def set_prs(self, *prs: tuple[int, str, str]) -> None:
        rows = [{"number": n, "headRefName": head, "state": state} for n, head, state in prs]
        self.set_gh(json.dumps(rows))

    def branch(self, name: str, merged: bool, push: bool = True, local: bool = True) -> str:
        """Create a branch with one commit, merged into main or not."""
        self.repo.git("checkout", "-q", "-b", name, "main")
        sha = self.repo.commit({f"{name}.txt": name}, message=name)
        if push:
            self.repo.git("push", "-q", "origin", name)
        self.repo.git("checkout", "-q", "main")
        if merged:
            self.repo.git("merge", "-q", "--ff-only", name)
            self.repo.git("push", "-q", "origin", "main")
        if not local:
            self.repo.git("branch", "-q", "-D", name)
        return sha

    def remote_branches(self) -> set[str]:
        output = self.repo.git("ls-remote", "--heads", "origin")
        return {line.split("refs/heads/")[1] for line in output.splitlines()}

    def local_branches(self) -> set[str]:
        return set(self.repo.git("branch", "--format=%(refname:short)").split())

    def remote_tags(self) -> set[str]:
        output = self.repo.git("ls-remote", "--tags", "origin")
        return {line.split("refs/tags/")[1] for line in output.splitlines()}

    def push_from_elsewhere(self, branch: str, delete: bool = False) -> str:
        """Change a branch on origin from another clone, as a teammate or agent would."""
        other = self.tmp_path / f"other-{branch}"
        env = {**os.environ, **GIT_ENV}

        def git(*args: str) -> str:
            result = subprocess.run(
                ["git", "-C", str(other), *args],
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
            return result.stdout.strip()

        subprocess.run(["git", "clone", "-q", str(self.origin), str(other)], check=True, env=env)
        if delete:
            git("push", "-q", "origin", "--delete", branch)
            return ""
        git("checkout", "-q", branch)
        (other / "late.txt").write_text("pushed after planning\n")
        git("add", "-A")
        git("commit", "-q", "-m", "late commit")
        git("push", "-q", "origin", branch)
        return git("rev-parse", "HEAD")

    def origin_sha(self, branch: str) -> str | None:
        output = self.repo.git("ls-remote", "origin", f"refs/heads/{branch}")
        return output.split()[0] if output else None
