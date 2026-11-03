"""The agent the loop drives: one session per model, one turn per prompt.

A session's token budget is enforced from the session's own totals (`GET /session/{id}`)
after every finished step, never by adding up step events: the event stream has no
replay, so a dropped connection would lose steps (docs/decisions/0002).
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
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


FILE_TOOLS = frozenset({"edit", "write", "multiedit", "patch"})


def turn_summary(tools: Counter[str], files: list[str]) -> str:
    """One line per turn: tool calls by name and the files edited or written."""
    calls = ", ".join(f"{name} {count}" for name, count in tools.most_common())
    total = sum(tools.values())
    used = f"{total} tool call{'s' if total != 1 else ''} ({calls})" if tools else "no tool calls"
    return f"  Agent: {used}; files edited: {', '.join(files) or 'none'}"


class OpenCodeAgent:
    """The `Agent` backed by an OpenCode server; summarizes each turn in one line."""

    def __init__(self, client: OpenCodeClient, show: Callable[[str], None]) -> None:
        self.client = client
        self.show = show
        self.directory: Path | None = None
        self.budgets: dict[str, int] = {}

    def start(self, spec: SessionSpec) -> str:
        self.client.check_health()
        self.directory = spec.directory
        session = self.client.create_session(spec)
        if spec.token_budget is not None:
            self.budgets[session] = spec.token_budget
        return session

    def over_budget(self, session: str) -> str | None:
        """Interrupt the session when its total is over budget, and say so."""
        budget = self.budgets.get(session)
        if budget is None:
            return None
        used = self.client.usage(session).tokens
        if used <= budget:
            return None
        self.client.interrupt(session)
        return f"token budget exceeded: {used:,} of {budget:,} tokens; interrupted"

    def relative(self, path: str) -> str:
        if self.directory is not None and Path(path).is_relative_to(self.directory):
            return str(Path(path).relative_to(self.directory))
        return path

    def turn(self, session: str, prompt: str) -> TurnResult:
        failure: str | None = None
        exceeded: str | None = None
        tools: Counter[str] = Counter()
        files: list[str] = []
        seen: set[str] = set()
        for event in self.client.run(session, prompt):
            part = as_object(event.data.get("part"))
            state = as_object(part.get("state"))
            done = state.get("status") in {"completed", "error"}
            if part.get("type") == "tool" and done and part.get("callID") not in seen:
                seen.add(str(part.get("callID")))
                tool = str(part.get("tool"))
                tools[tool] += 1
                path = as_object(state.get("input")).get("filePath")
                if (
                    tool in FILE_TOOLS
                    and isinstance(path, str)
                    and self.relative(path) not in files
                ):
                    files.append(self.relative(path))
            elif part.get("type") == "step-finish" and exceeded is None:
                exceeded = self.over_budget(session)
                if exceeded is not None:
                    self.show(f"  {exceeded}")
            elif event.type == "session.error" and exceeded is None:
                failure = error_message(event)
                self.show(f"  error: {failure}")
        self.show(turn_summary(tools, files))
        return TurnResult(exceeded or failure)

    def usage(self, session: str) -> Usage:
        return self.client.usage(session)
