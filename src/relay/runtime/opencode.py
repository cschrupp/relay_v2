"""Drive one OpenCode agent session over OpenCode's v2 HTTP API (`/api/...`).

Each session names its OpenCode agent (the role) and its provider and model explicitly;
nothing is inherited from the server's defaults. A run is: create the session, admit a
prompt, stream the session's durable events from that prompt on until the agent loop is
idle, then read token usage and the cost OpenCode reports.

"Idle" is decided by OpenCode's active-session list, checked after every finished step
and whenever the event stream goes quiet. The stream is resumed from the last event id
when it drops, so no event is lost.
"""

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import quote

import httpx

from relay.runtime.sse import parse_sse

STEP_BOUNDARIES = frozenset({"session.next.step.ended", "session.next.step.failed"})
DEFAULT_IDLE_CHECK_SECONDS = 5.0
QUIET_CHECKS_BEFORE_IDLE = 3
REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

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
    id: str | None
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


def to_event(frame_event: str | None, frame_id: str | None, text: str) -> SessionEvent | None:
    """Decode one durable event frame; frames that are not JSON objects are skipped.

    OpenCode puts the event's sequence in `durable.seq`, not in the SSE `id:` field; that
    sequence is the event id, so a dropped stream resumes with `after=<seq>`.
    """
    try:
        payload = as_object(json.loads(text))
    except json.JSONDecodeError:
        return None
    kind = payload.get("type") or frame_event
    if not isinstance(kind, str):
        return None
    sequence = as_object(payload.get("durable")).get("seq")
    event_id = str(sequence) if isinstance(sequence, int) else frame_id
    data = as_object(payload.get("data")) or payload
    return SessionEvent(event_id, kind, data)


def usage_from(session: dict[str, Any]) -> Usage:
    """Token usage and the cost OpenCode reports for a v2 session (source "runtime")."""
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


class OpenCodeClient:
    """One OpenCode server. Not thread-safe; use one client per run."""

    def __init__(
        self,
        base_url: str,
        transport: httpx.BaseTransport | None = None,
        idle_check_seconds: float = DEFAULT_IDLE_CHECK_SECONDS,
        reconnect_delay: float = 0.5,
    ) -> None:
        self.http = httpx.Client(base_url=base_url, transport=transport, timeout=REQUEST_TIMEOUT)
        self.idle_check_seconds = idle_check_seconds
        self.reconnect_delay = reconnect_delay

    def close(self) -> None:
        self.http.close()

    def request(
        self, method: str, path: str, body: object = None, expect: int = 200
    ) -> httpx.Response:
        try:
            response = self.http.request(method, path, json=body)
        except httpx.HTTPError as error:
            raise OpenCodeError(f"{method} {path} failed: {error}") from error
        if response.status_code != expect:
            detail = response.text[:200]
            message = f"{method} {path} returned {response.status_code}: {detail}"
            raise OpenCodeError(message, response.status_code)
        return response

    def data(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = as_object(response.json())
        except ValueError as error:
            raise OpenCodeError(f"{response.url.path} returned invalid JSON") from error
        data = payload.get("data")
        if not isinstance(data, dict):
            raise OpenCodeError(f"{response.url.path} returned no data object")
        return cast(dict[str, Any], data)

    def check_health(self) -> None:
        payload = as_object(self.request("GET", "/api/health").json())
        if payload.get("healthy") is not True:
            raise OpenCodeError(f"OpenCode reports itself unhealthy: {payload}")

    def agents(self, directory: Path) -> list[str]:
        """Agents OpenCode knows for a directory, including the project's own."""
        params = {"location[directory]": str(directory)}
        try:
            response = self.http.get("/api/agent", params=params)
        except httpx.HTTPError as error:
            raise OpenCodeError(f"GET /api/agent failed: {error}") from error
        if response.status_code != 200:
            raise OpenCodeError(
                f"GET /api/agent returned {response.status_code}", response.status_code
            )
        rows: object = as_object(response.json()).get("data")
        if not isinstance(rows, list):
            return []
        return [str(as_object(row).get("id")) for row in cast(list[object], rows)]

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
        body = {
            "agent": spec.agent,
            "model": {"id": spec.model, "providerID": spec.provider},
            "location": {"directory": str(spec.directory)},
        }
        session = self.data(self.request("POST", "/api/session", body))
        model = as_object(session.get("model"))
        confirmed = (
            as_object(session.get("location")).get("directory") == str(spec.directory)
            and (model.get("providerID"), model.get("id")) == (spec.provider, spec.model)
            and session.get("agent", spec.agent) == spec.agent
        )
        session_id = session.get("id")
        if not isinstance(session_id, str) or not confirmed:
            raise OpenCodeError(f"OpenCode did not confirm the requested session: {session}")
        return session_id

    def prompt(self, session_id: str, text: str) -> int:
        """Admit a prompt and return its admission sequence number."""
        path = f"/api/session/{quote(session_id, safe='')}/prompt"
        receipt = self.data(self.request("POST", path, {"prompt": {"text": text}}))
        sequence = receipt.get("admittedSeq")
        if not isinstance(sequence, int):
            raise OpenCodeError(f"prompt receipt has no admission sequence: {receipt}")
        return sequence

    def events(self, session_id: str, after: str | None) -> Iterator[SessionEvent]:
        """Stream durable events after a sequence; ends when the stream closes or goes quiet."""
        path = f"/api/session/{quote(session_id, safe='')}/event"
        params = {"after": after} if after is not None else {}
        timeout = httpx.Timeout(10.0, read=self.idle_check_seconds)
        try:
            with self.http.stream("GET", path, params=params, timeout=timeout) as response:
                if response.status_code != 200:
                    response.read()
                    raise OpenCodeError(f"GET {path} returned {response.status_code}")
                for frame in parse_sse(response.iter_lines()):
                    event = to_event(frame.event, frame.id, frame.data)
                    if event is not None:
                        yield event
        except httpx.ReadTimeout:
            return
        except httpx.HTTPError as error:
            raise OpenCodeError(f"GET {path} failed: {error}") from error

    def is_active(self, session_id: str) -> bool:
        return session_id in self.data(self.request("GET", "/api/session/active"))

    def run_events(self, session_id: str, after: int) -> Iterator[SessionEvent]:
        """Yield the events of the run admitted at `after` until the agent loop is idle."""
        cursor, stepped, quiet = str(after), False, 0
        while True:
            seen = False
            for event in self.events(session_id, cursor):
                cursor, seen, quiet = event.id or cursor, True, 0
                yield event
                if event.type in STEP_BOUNDARIES:
                    stepped = True
                    if not self.is_active(session_id):
                        return
            quiet += 0 if seen else 1
            if not self.is_active(session_id):
                if stepped:
                    return
                if quiet >= QUIET_CHECKS_BEFORE_IDLE:
                    message = f"session {session_id} went idle without running a step"
                    raise OpenCodeError(f"{message}; see the OpenCode server log")
            if not seen:
                time.sleep(self.reconnect_delay)

    def interrupt(self, session_id: str) -> None:
        """Stop the session's active run; a no-op when it is already idle."""
        self.request("POST", f"/api/session/{quote(session_id, safe='')}/interrupt", expect=204)

    def usage(self, session_id: str) -> Usage:
        return usage_from(
            self.data(self.request("GET", f"/api/session/{quote(session_id, safe='')}"))
        )
