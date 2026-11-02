"""Drive one OpenCode agent session over OpenCode's session HTTP API.

This is the API `opencode run` uses (`/session`, `/session/{id}/prompt_async`, `/event`).
OpenCode 1.18 also has a v2 API (`/api/session`), but its runner only sees providers in
the v2 model registry, so models from providers you signed in to (OpenRouter, for
example) fail there with "Model unavailable" while the CLI runs them fine.

Each session names its OpenCode agent (the role) and its provider and model explicitly.
A turn subscribes to the directory's event stream, admits the prompt, yields the
session's events and ends at `session.idle`. If the stream goes quiet, the session's
status decides whether to keep waiting. Usage is the session's cumulative tokens and
the cost OpenCode reports.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import quote

import httpx

from relay.runtime.sse import parse_sse

DEFAULT_IDLE_CHECK_SECONDS = 30.0
REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
BUSY_STATES = frozenset({"busy", "retry"})

CostSource = Literal["runtime"]


class OpenCodeError(RuntimeError):
    """OpenCode was unreachable, refused a request, or answered in an unexpected shape."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class SessionSpec:
    directory: Path
    agent: str
    provider: str
    model: str


@dataclass(frozen=True)
class SessionEvent:
    type: str
    data: dict[str, Any]


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: Decimal | None
    cost_source: CostSource | None


def as_object(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def as_count(value: object) -> int:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0


def to_event(text: str) -> SessionEvent | None:
    """Decode one `{type, properties}` frame; anything else is skipped."""
    try:
        payload = as_object(json.loads(text))
    except json.JSONDecodeError:
        return None
    kind = payload.get("type")
    if not isinstance(kind, str):
        return None
    return SessionEvent(kind, as_object(payload.get("properties")))


def event_session(event: SessionEvent) -> str | None:
    info, part = as_object(event.data.get("info")), as_object(event.data.get("part"))
    for container in (event.data, info, part):
        session = container.get("sessionID")
        if isinstance(session, str):
            return session
    return None


def error_message(event: SessionEvent) -> str:
    """The readable message of a `session.error` event."""
    error = as_object(event.data.get("error"))
    message = as_object(error.get("data")).get("message") or error.get("name")
    return str(message or "unknown error")


def is_step_start(event: SessionEvent) -> bool:
    part = as_object(event.data.get("part"))
    return event.type == "message.part.updated" and part.get("type") == "step-start"


def usage_from(session: dict[str, Any]) -> Usage:
    """Token usage and the cost OpenCode reports for a session (source "runtime")."""
    tokens = as_object(session.get("tokens"))
    cache = as_object(tokens.get("cache"))
    cost = session.get("cost")
    reported = isinstance(cost, int | float) and not isinstance(cost, bool) and cost >= 0
    return Usage(
        input_tokens=as_count(tokens.get("input")),
        output_tokens=as_count(tokens.get("output")),
        reasoning_tokens=as_count(tokens.get("reasoning")),
        cache_read_tokens=as_count(cache.get("read")),
        cache_write_tokens=as_count(cache.get("write")),
        cost_usd=Decimal(str(cost)) if reported else None,
        cost_source="runtime" if reported else None,
    )


def no_step_error(spec: SessionSpec, error: str | None) -> OpenCodeError:
    """Explain a turn in which OpenCode never started a model step, with what to check."""
    model = f"{spec.provider}/{spec.model}"
    reason = f": {error}" if error else ""
    return OpenCodeError(
        f"OpenCode went idle without running a step with {model}{reason}\n"
        "Check:\n"
        f'  1. opencode run --model {model} "reply with ok"   (does the model answer?)\n'
        "  2. restart the server with `opencode serve --print-logs` and read its error\n"
        f"  3. `opencode models {spec.provider}` lists {spec.model}"
    )


class OpenCodeClient:
    """One OpenCode server. Not thread-safe; use one client per run."""

    def __init__(
        self,
        base_url: str,
        transport: httpx.BaseTransport | None = None,
        idle_check_seconds: float = DEFAULT_IDLE_CHECK_SECONDS,
    ) -> None:
        self.http = httpx.Client(base_url=base_url, transport=transport, timeout=REQUEST_TIMEOUT)
        self.idle_check_seconds = idle_check_seconds
        self.sessions: dict[str, SessionSpec] = {}

    def close(self) -> None:
        self.http.close()

    def request(
        self, method: str, path: str, directory: Path, body: object = None, expect: int = 200
    ) -> httpx.Response:
        params = {"directory": str(directory)}
        try:
            response = self.http.request(method, path, params=params, json=body)
        except httpx.HTTPError as error:
            raise OpenCodeError(f"{method} {path} failed: {error}") from error
        if response.status_code != expect:
            message = f"{method} {path} returned {response.status_code}: {response.text[:200]}"
            raise OpenCodeError(message, response.status_code)
        return response

    def check_health(self) -> None:
        try:
            payload = as_object(self.http.get("/global/health").json())
        except (httpx.HTTPError, ValueError) as error:
            raise OpenCodeError(f"GET /global/health failed: {error}") from error
        if payload.get("healthy") is not True:
            raise OpenCodeError(f"OpenCode reports itself unhealthy: {payload}")

    def agents(self, directory: Path) -> list[str]:
        """Agents OpenCode knows for a directory, including the project's own."""
        rows: object = self.request("GET", "/agent", directory).json()
        if not isinstance(rows, list):
            return []
        return [str(as_object(row).get("name")) for row in cast(list[object], rows)]

    def create_session(self, spec: SessionSpec) -> str:
        """Create a session with the spec's agent, provider and model; return its id.

        OpenCode accepts unknown agent names silently, so the agent is checked first.
        """
        known = self.agents(spec.directory)
        if spec.agent not in known:
            available = ", ".join(sorted(known)) or "none"
            raise OpenCodeError(
                f"OpenCode has no agent {spec.agent!r} here (available: {available})"
            )
        body = {"agent": spec.agent, "model": {"id": spec.model, "providerID": spec.provider}}
        session = as_object(self.request("POST", "/session", spec.directory, body).json())
        model = as_object(session.get("model"))
        confirmed = (
            session.get("directory") == str(spec.directory)
            and session.get("agent") == spec.agent
            and (model.get("providerID"), model.get("id")) == (spec.provider, spec.model)
        )
        session_id = session.get("id")
        if not isinstance(session_id, str) or not confirmed:
            raise OpenCodeError(f"OpenCode did not confirm the requested session: {session}")
        self.sessions[session_id] = spec
        return session_id

    def spec_for(self, session: str) -> SessionSpec:
        if session not in self.sessions:
            raise OpenCodeError(f"session {session} was not created by this client")
        return self.sessions[session]

    def prompt(self, session: str, text: str) -> None:
        spec = self.spec_for(session)
        body = {
            "agent": spec.agent,
            "model": {"providerID": spec.provider, "modelID": spec.model},
            "parts": [{"type": "text", "text": text}],
        }
        path = f"/session/{quote(session, safe='')}/prompt_async"
        self.request("POST", path, spec.directory, body, expect=204)

    def is_busy(self, session: str) -> bool:
        directory = self.spec_for(session).directory
        statuses = as_object(self.request("GET", "/session/status", directory).json())
        return as_object(statuses.get(session)).get("type") in BUSY_STATES

    def stream(self, session: str, prompt: str | None) -> Iterator[SessionEvent]:
        """The session's events from one connection; sends the prompt once subscribed."""
        params = {"directory": str(self.spec_for(session).directory)}
        timeout = httpx.Timeout(10.0, read=self.idle_check_seconds)
        try:
            with self.http.stream("GET", "/event", params=params, timeout=timeout) as response:
                if response.status_code != 200:
                    raise OpenCodeError(f"GET /event returned {response.status_code}")
                if prompt is not None:
                    self.prompt(session, prompt)
                for frame in parse_sse(response.iter_lines()):
                    event = to_event(frame.data)
                    if event is not None and event_session(event) == session:
                        yield event
                        if event.type == "session.idle":
                            return
        except httpx.ReadTimeout:
            return
        except httpx.HTTPError as error:
            raise OpenCodeError(f"GET /event failed: {error}") from error

    def run(self, session: str, prompt: str) -> Iterator[SessionEvent]:
        """Admit a prompt and yield the session's events until it is idle again."""
        pending: str | None = prompt
        stepped, error, idle = False, None, False
        while not idle:
            for event in self.stream(session, pending):
                stepped = stepped or is_step_start(event)
                if event.type == "session.error":
                    error = error_message(event)
                idle = event.type == "session.idle"
                yield event
            pending = None
            idle = idle or not self.is_busy(session)
        if not stepped:
            raise no_step_error(self.spec_for(session), error)

    def interrupt(self, session: str) -> None:
        """Abort the session's running turn; a no-op when it is idle."""
        path = f"/session/{quote(session, safe='')}/abort"
        self.request("POST", path, self.spec_for(session).directory)

    def usage(self, session: str) -> Usage:
        path = f"/session/{quote(session, safe='')}"
        payload = self.request("GET", path, self.spec_for(session).directory).json()
        return usage_from(as_object(payload))
