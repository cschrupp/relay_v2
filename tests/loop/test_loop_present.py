import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from loop_fixture import SETTINGS, FakeAgent, FakePublisher, ScriptedConsole, git, packet, repo

from relay.loop.agent import OpenCodeAgent
from relay.loop.present import Spend, pull_request_body, pull_request_title
from relay.loop.publish import issue_title
from relay.loop.steer import run_packet
from relay.runtime.opencode import SessionEvent, SessionSpec

__all__ = ["repo"]

SPEND = Spend(
    "openrouter/deepseek/deepseek-v4.1-flash", 23056, 1826, Decimal("0.003679504"), "runtime"
)


def tool(call: str, name: str, path: str | None = None, status: str = "completed") -> SessionEvent:
    state = {"status": status, "input": {"filePath": path} if path else {}}
    part = {"type": "tool", "callID": call, "tool": name, "state": state}
    return SessionEvent("message.part.updated", {"part": part})


class ToolClient:
    def check_health(self) -> None: ...

    def create_session(self, spec: SessionSpec) -> str:
        return "ses_1"

    def run(self, session: str, prompt: str) -> Iterator[SessionEvent]:
        yield tool("c1", "read", "/w/src/relay/cli/main.py")
        yield tool("c2", "edit", "/w/src/relay/cli/main.py", status="running")
        yield tool("c2", "edit", "/w/src/relay/cli/main.py")
        yield tool("c2", "edit", "/w/src/relay/cli/main.py")
        yield tool("c3", "write", "/w/tests/cli/test_cli_version.py")
        yield tool("c4", "bash", status="error")
        yield tool("c5", "edit", "/elsewhere/x.py")


def test_turn_is_summarized_in_one_line() -> None:
    shown: list[str] = []
    agent = OpenCodeAgent(ToolClient(), shown.append)  # type: ignore[arg-type]

    agent.turn(agent.start(SessionSpec(Path("/w"), "implementer", "p", "m")), "go")

    assert shown == [
        "  Agent: 5 tool calls (edit 2, read 1, write 1, bash 1); files edited: "
        "src/relay/cli/main.py, tests/cli/test_cli_version.py, /elsewhere/x.py"
    ]


def test_spend_text() -> None:
    assert SPEND.text() == (
        "openrouter/deepseek/deepseek-v4.1-flash, 23,056 tokens in, 1,826 out, $0.0037 (runtime)"
    )
    unknown = Spend("p/m", 5, 1, None, None)
    assert unknown.text() == "p/m, 5 tokens in, 1 out, cost not reported"


@pytest.mark.parametrize(
    ("goal", "issue", "title"),
    [
        ("anything", "Add relay --version", "Add relay --version"),
        ('Add `relay --version`: it prints "relay <version>"', None, "Add `relay --version`"),
        ("Fix the lease. Then add a test", None, "Fix the lease"),
        (
            "Read importlib.metadata for the version",
            None,
            "Read importlib.metadata for the version",
        ),
        ("word " * 30, None, ("word " * 14).strip()),
        ("x", "Issue " + "y" * 80, "Issue"),
    ],
)
def test_pull_request_title(repo: Path, goal: str, issue: str | None, title: str) -> None:
    result = pull_request_title(packet(repo, goal=goal), issue)

    assert result == title
    assert len(result) <= 70


def test_pull_request_body_keeps_the_goal_and_shows_the_total(repo: Path) -> None:
    body = pull_request_body(packet(repo), "a" * 40, "CARD", None, SPEND, 2)

    assert body.startswith("Closes #8\n\nAdd a helper to low\n\nBase: `" + "a" * 40 + "`")
    assert f"Agent: {SPEND.text()} over 2 attempt(s)" in body


def test_run_shows_spend_on_the_card_and_titles_from_the_issue(repo: Path) -> None:
    console = ScriptedConsole("redirect smaller", "accept")
    publisher = FakePublisher()
    agent = FakeAgent({"src/pkg/low/helper.py": "y = 1\n"}, {})
    titles: list[int] = []

    def lookup(number: int) -> str:
        titles.append(number)
        return "Add a helper"

    run_packet(repo, packet(repo), SETTINGS, agent, publisher, console, lookup)

    line = "  Agent: anthropic/claude-sonnet-5-5, 1,000 tokens in, 100 out, $0.0100 (runtime)"
    assert console.text().count(line) == 2
    [(_, title, body)] = publisher.published
    assert (titles, title) == ([8], "Add a helper")
    total = "anthropic/claude-sonnet-5-5, 2,000 tokens in, 200 out, $0.0200 (runtime)"
    assert f"Agent: {total} over 2 attempt(s)" in body
    assert "Add a helper to low" in body
    subject = git(repo, "log", "-1", "--format=%s", "relay/8-add-a-helper-to-low")
    assert subject == "relay: Add a helper (attempt 1)"


def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: str, code: int) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(f"#!/bin/sh\necho '{output}'\nexit {code}\n")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def test_issue_title_from_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_gh(tmp_path, monkeypatch, "Add relay --version", 0)

    assert issue_title(tmp_path, 21) == "Add relay --version"


def test_issue_title_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_gh(tmp_path, monkeypatch, "not found", 1)

    assert issue_title(tmp_path, 21) is None
