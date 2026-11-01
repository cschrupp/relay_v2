import os
import subprocess
from pathlib import Path

import pytest

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.com",
    "GIT_COMMITTER_NAME": "Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


class FixtureRepo:
    """A throwaway git repository whose commits are built from {path: text} maps."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.path), *args],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, **GIT_ENV},
        )
        return result.stdout.strip()

    def commit(self, files: dict[str, str | None], message: str = "change") -> str:
        """Write (or delete, for None) files, commit everything and return the SHA."""
        for relative, text in files.items():
            target = self.path / relative
            if text is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> FixtureRepo:
    return FixtureRepo(tmp_path / "repo")


def long_function(name: str, lines: int) -> str:
    """Source for a function that is exactly `lines` lines long."""
    body = "".join(f"    x{i} = {i}\n" for i in range(lines - 2))
    return f"def {name}():\n{body}    return 0\n"
