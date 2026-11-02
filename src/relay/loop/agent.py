"""The agent the loop drives: one session per packet, one turn per prompt."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from relay.runtime.opencode import OpenCodeClient, SessionSpec, Usage, as_object, error_message


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
        for event in self.client.run(session, prompt):
            part = as_object(event.data.get("part"))
            state = as_object(part.get("state"))
            if part.get("type") == "tool" and state.get("status") in {"completed", "error"}:
                self.show(f"  tool: {part.get('tool')} ({state.get('status')})")
            elif event.type == "session.error":
                failure = error_message(event)
                self.show(f"  error: {failure}")
        return TurnResult(failure)

    def usage(self, session: str) -> Usage:
        return self.client.usage(session)
