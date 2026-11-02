"""The agent the loop drives: one session per packet, one turn per prompt."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from relay.runtime.opencode import OpenCodeClient, SessionSpec, Usage, as_object


@dataclass(frozen=True)
class TurnResult:
    """How a turn ended: `failure` is the agent's error message when a step failed."""

    failure: str | None = None


class Agent(Protocol):
    def start(self, spec: SessionSpec) -> str: ...

    def turn(self, session: str, prompt: str) -> TurnResult: ...

    def usage(self, session: str) -> Usage: ...


class OpenCodeAgent:
    """The `Agent` backed by an OpenCode server; shows tool calls and step ends as they come."""

    def __init__(self, client: OpenCodeClient, show: Callable[[str], None]) -> None:
        self.client = client
        self.show = show

    def start(self, spec: SessionSpec) -> str:
        self.client.check_health()
        return self.client.create_session(spec)

    def turn(self, session: str, prompt: str) -> TurnResult:
        failure: str | None = None
        for event in self.client.run_events(session, self.client.prompt(session, prompt)):
            if event.type == "session.next.tool.called":
                self.show(f"  tool: {event.data.get('tool')}")
            elif event.type == "session.next.step.failed":
                error = as_object(event.data.get("error"))
                failure = str(error.get("message") or event.data.get("error"))
                self.show(f"  step failed: {failure}")
        return TurnResult(failure)

    def usage(self, session: str) -> Usage:
        return self.client.usage(session)
