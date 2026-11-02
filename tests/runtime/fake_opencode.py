"""A scripted OpenCode v2 server for httpx.MockTransport, using the wire format seen live."""

import json
from typing import Any

import httpx

SESSION = "ses_1"


def frame(seq: int, kind: str, data: dict[str, Any] | None = None) -> str:
    payload = {
        "id": f"evt_{seq}",
        "type": kind,
        "durable": {"aggregateID": SESSION, "seq": seq, "version": 1},
        "data": {"sessionID": SESSION, **(data or {})},
    }
    return f"data: {json.dumps(payload)}\n\n"


class FakeOpenCode:
    def __init__(self) -> None:
        self.agents = ["build", "implementer", "reviewer"]
        self.events: list[tuple[int, str, dict[str, Any]]] = []
        self.stream_batches: list[int] = []  # max seq served per stream request, in order
        self.active_checks_until_idle = 0
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

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path in self.status_overrides:
            return httpx.Response(self.status_overrides[path], text="refused")
        if path == "/api/health":
            return httpx.Response(200, json={"healthy": True})
        if path == "/api/agent":
            return httpx.Response(200, json={"data": [{"id": a} for a in self.agents]})
        if path == "/api/session" and request.method == "POST":
            body = json.loads(request.content)
            session = {
                "id": SESSION,
                "agent": body["agent"],
                "location": body["location"],
                "model": {**body["model"], "variant": "default"},
                **self.override_session,
            }
            return httpx.Response(200, json={"data": session})
        if path == f"/api/session/{SESSION}/prompt":
            return httpx.Response(
                200, json={"data": {"admittedSeq": 1, "id": "msg_1", "sessionID": SESSION}}
            )
        if path == f"/api/session/{SESSION}/event":
            return self.stream(int(request.url.params.get("after", "0")))
        if path == "/api/session/active":
            running = self.active_checks_until_idle > 0
            self.active_checks_until_idle -= 1
            return httpx.Response(
                200, json={"data": {SESSION: {"type": "running"}} if running else {}}
            )
        if path == f"/api/session/{SESSION}/interrupt":
            return httpx.Response(204)
        if path == f"/api/session/{SESSION}":
            return httpx.Response(200, json={"data": {"id": SESSION, **self.session}})
        return httpx.Response(404, text="no route")

    def stream(self, after: int) -> httpx.Response:
        limit = self.stream_batches.pop(0) if self.stream_batches else 10**9
        body = "".join(
            frame(seq, kind, data) for seq, kind, data in self.events if after < seq <= limit
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)
