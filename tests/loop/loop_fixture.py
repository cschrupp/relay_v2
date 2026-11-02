"""Fixture repository, fake agent, fake publisher and scripted console for loop tests."""

import os
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from relay.domain import LineEstimate, WorkPacket
from relay.loop.agent import TurnResult
from relay.loop.steer import AgentSettings, Console
from relay.loop.workspace import Workspace
from relay.runtime.opencode import SessionSpec, Usage

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.com",
    "GIT_COMMITTER_NAME": "Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}
IMPORTLINTER = """[importlinter]
root_package = pkg

[importlinter:contract:layers]
name = Pkg layers
type = layers
layers =
    pkg.high
    pkg.low
"""
BASE_FILES = {
    "src/pkg/__init__.py": "",
    "src/pkg/high/__init__.py": "from pkg.low import x\n",
    "src/pkg/low/__init__.py": "x = 1\n",
    "tests/test_low.py": "def test_low():\n    pass\n",
    ".importlinter": IMPORTLINTER,
    "README.md": "readme\n",
}
SETTINGS = AgentSettings("implementer", "anthropic", "claude-sonnet-5-5")

Edits = dict[str, str | None]


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    for relative, text in BASE_FILES.items():
        (path / relative).parent.mkdir(parents=True, exist_ok=True)
        (path / relative).write_text(text)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "base")
    return path


def packet(repo: Path, **changes: object) -> WorkPacket:
    fields: dict[str, object] = {
        "goal": "Add a helper to low",
        "base_sha": git(repo, "rev-parse", "--short", "HEAD"),
        "allowed_paths": ("src/pkg/**", "tests/**"),
        "expected_lines": LineEstimate(source=20, tests=20),
        "acceptance_commands": ("test -f src/pkg/low/helper.py",),
        "token_budget": 100000,
        "role": "implementer",
        "tier": "cheap",
        "issue": 8,
    }
    return WorkPacket.model_validate({**fields, **changes})


class FakeAgent:
    """Applies one scripted set of file edits per turn to the session's directory."""

    def __init__(self, *turns: Edits) -> None:
        self.turns = list(turns)
        self.prompts: list[str] = []
        self.blocked_writes: list[str] = []
        self.spec: SessionSpec | None = None

    def start(self, spec: SessionSpec) -> str:
        self.spec = spec
        return "ses_fake"

    def turn(self, session: str, prompt: str) -> TurnResult:
        assert self.spec is not None
        self.prompts.append(prompt)
        for relative, text in self.turns.pop(0).items():
            target = self.spec.directory / relative
            try:
                if text is None:
                    target.unlink()
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(text)
            except PermissionError:
                self.blocked_writes.append(relative)
        return TurnResult()

    def usage(self, session: str) -> Usage:
        done = len(self.prompts)
        return Usage(1000 * done, 100 * done, 0, 0, 0, Decimal("0.01") * done, "runtime")


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, str]] = []

    def publish(self, workspace: Workspace, title: str, body: str) -> str:
        self.published.append((workspace.branch, title, body))
        return "https://github.test/pr/1"


class ScriptedConsole(Console):
    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.shown: list[str] = []
        self.questions: list[str] = []
        super().__init__(ask=self.answer, show=self.shown.append)

    def answer(self, question: str) -> str:
        self.questions.append(question)
        return self.answers.pop(0)

    def text(self) -> str:
        return "\n".join(self.shown)
