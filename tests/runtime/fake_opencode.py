"""A scripted OpenCode session-API server for httpx.MockTransport, in the wire format seen live."""

import json
from typing import Any

import httpx

SESSION = "ses_1"


def frame(kind: str, properties: dict[str, Any] | None = None) -> str:
    payload = {"type": kind, "properties": {"sessionID": SESSION, **(properties or {})}}
    return f"data: {json.dumps(payload)}\n\n"


STEP_START = ("message.part.updated", {"part": {"type": "step-start", "sessionID": SESSION}})
IDLE = ("session.idle", {})


class FakeOpenCode:
    def __init__(self) -> None:
        self.agents = ["build", "implementer", "reviewer"]
        self.event_batches: list[list[tuple[str, dict[str, Any]]]] = [[STEP_START, IDLE]]
        self.busy_checks = 0
        self.requests: list[httpx.Request] = []
        self.session: dict[str, Any] = {
            "cost": 0.0123,
            "tokens": {
                "input": 1200,
                "output": 300,
                "reasoning": 40,
                "cache": {"read": 900, "write": 10},
            },
        }
        self.override_session: dict[str, Any] = {}
        self.status_overrides: dict[str, int] = {}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def bodies(self, path: str) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.url.path == path and r.content]

    def paths(self) -> list[str]:
        return [f"{r.method} {r.url.path}" for r in self.requests]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path in self.status_overrides:
            return httpx.Response(self.status_overrides[path], text="refused")
        routes = {
            "/global/health": lambda: httpx.Response(
                200, json={"healthy": True, "version": "1.18.23"}
            ),
            "/agent": lambda: httpx.Response(200, json=[{"name": a} for a in self.agents]),
            "/session": lambda: self.create(request),
            "/event": self.stream,
            f"/session/{SESSION}/prompt_async": lambda: httpx.Response(204),
            "/session/status": self.status,
            f"/session/{SESSION}/abort": lambda: httpx.Response(200, json=True),
            f"/session/{SESSION}": lambda: httpx.Response(
                200, json={"id": SESSION, **self.session}
            ),
        }
        return routes[path]() if path in routes else httpx.Response(404, text="no route")

    def create(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        session = {
            "id": SESSION,
            "directory": request.url.params["directory"],
            "agent": body["agent"],
            "model": body["model"],
            **self.override_session,
        }
        return httpx.Response(200, json=session)

    def stream(self) -> httpx.Response:
        batch = self.event_batches.pop(0) if self.event_batches else []
        body = "".join(frame(kind, props) for kind, props in batch)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)

    def status(self) -> httpx.Response:
        busy = self.busy_checks > 0
        self.busy_checks -= 1
        return httpx.Response(200, json={SESSION: {"type": "busy"}} if busy else {})
