from collections.abc import Iterator
from pathlib import Path

import pytest

from relay.cli.main import main
from relay.loop.agent import OpenCodeAgent
from relay.loop.workspace import slug
from relay.runtime.opencode import SessionEvent, SessionSpec


class StubClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def check_health(self) -> None:
        self.calls.append("health")

    def create_session(self, spec: SessionSpec) -> str:
        self.calls.append(f"create {spec.agent}")
        return "ses_1"

    def prompt(self, session: str, text: str) -> int:
        self.calls.append(f"prompt {text}")
        return 4

    def run_events(self, session: str, after: int) -> Iterator[SessionEvent]:
        self.calls.append(f"events after {after}")
        yield SessionEvent("5", "session.next.tool.called", {"tool": "edit"})
        yield SessionEvent("6", "session.next.step.failed", {"error": {"message": "HTTP 400"}})


def test_opencode_agent_reports_tools_and_failures() -> None:
    client = StubClient()
    shown: list[str] = []
    agent = OpenCodeAgent(client, shown.append)  # type: ignore[arg-type]

    session = agent.start(SessionSpec(Path("/w"), "implementer", "p", "m"))
    turn = agent.turn(session, "do it")

    assert client.calls == ["health", "create implementer", "prompt do it", "events after 4"]
    assert turn.failure == "HTTP 400"
    assert shown == ["  tool: edit", "  step failed: HTTP 400"]


@pytest.mark.parametrize(
    ("goal", "expected"),
    [
        ("Add a helper to low", "add-a-helper-to-low"),
        ("  Fix: the `relay tidy` lease!  ", "fix-the-relay-tidy-lease"),
        ("!!!", "packet"),
        ("x" * 60, "x" * 40),
    ],
)
def test_slug(goal: str, expected: str) -> None:
    assert slug(goal) == expected


def test_cli_rejects_a_model_without_provider() -> None:
    with pytest.raises(SystemExit):
        main(["run", "packet.yaml", "--model", "just-a-model"])


def test_cli_reports_an_invalid_packet(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    packet = tmp_path / "packet.yaml"
    packet.write_text("goal: x\n")

    code = main(["run", str(packet), "--model", "anthropic/claude"])

    assert code == 2
    assert "relay run stopped" in capsys.readouterr().out
