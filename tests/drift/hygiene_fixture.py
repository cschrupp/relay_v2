import json
import os
from pathlib import Path

import pytest
from conftest import FixtureRepo


class RemoteRepo:
    """A fixture repo with a bare `origin` remote, branches and a fake `gh` on PATH."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
