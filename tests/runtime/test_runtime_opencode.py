from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fake_opencode import SESSION, FakeOpenCode

from relay.runtime.opencode import OpenCodeClient, OpenCodeError, SessionSpec, Usage, to_event

SPEC = SessionSpec(Path("/work/repo"), "implementer", "anthropic", "claude-sonnet-5-5")


@pytest.fixture
def fake() -> FakeOpenCode:
    return FakeOpenCode()


def client_for(fake: FakeOpenCode) -> OpenCodeClient:
    return OpenCodeClient(
        "http://opencode.test", fake.transport(), idle_check_seconds=0.1, reconnect_delay=0
    )


def test_health(fake: FakeOpenCode) -> None:
    client_for(fake).check_health()


def test_unreachable_server_is_an_opencode_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = OpenCodeClient("http://opencode.test", httpx.MockTransport(refuse))

    with pytest.raises(OpenCodeError, match="connection refused"):
        client.check_health()


def test_each_session_names_its_own_agent_provider_and_model(fake: FakeOpenCode) -> None:
    client = client_for(fake)
    reviewer = SessionSpec(Path("/work/repo"), "reviewer", "openai", "gpt-6")

    assert client.create_session(SPEC) == SESSION
    assert client.create_session(reviewer) == SESSION

    assert fake.bodies("/api/session") == [
        {
            "agent": "implementer",
            "model": {"id": "claude-sonnet-5-5", "providerID": "anthropic"},
            "location": {"directory": "/work/repo"},
        },
        {
            "agent": "reviewer",
            "model": {"id": "gpt-6", "providerID": "openai"},
            "location": {"directory": "/work/repo"},
        },
    ]
    [agent_query, *_] = [r for r in fake.requests if r.url.path == "/api/agent"]
    assert agent_query.url.params["location[directory]"] == "/work/repo"


def test_unknown_agent_is_rejected_before_creating_a_session(fake: FakeOpenCode) -> None:
    with pytest.raises(OpenCodeError, match="no agent 'implementr'.*implementer"):
        client_for(fake).create_session(
            SessionSpec(Path("/work/repo"), "implementr", "anthropic", "m")
        )

    assert fake.bodies("/api/session") == []


@pytest.mark.parametrize(
    "override",
    [
        {"model": {"id": "other-model", "providerID": "anthropic"}},
        {"location": {"directory": "/elsewhere"}},
        {"agent": "build"},
        {"id": None},
    ],
)
def test_session_that_does_not_match_the_request_is_rejected(
    fake: FakeOpenCode, override: dict[str, object]
) -> None:
    fake.override_session = override

    with pytest.raises(OpenCodeError, match="did not confirm"):
        client_for(fake).create_session(SPEC)


def test_refused_request_carries_the_status(fake: FakeOpenCode) -> None:
    fake.status_overrides["/api/session"] = 401

    with pytest.raises(OpenCodeError) as error:
        client_for(fake).create_session(SPEC)

    assert error.value.status == 401


def test_prompt_returns_the_admission_sequence(fake: FakeOpenCode) -> None:
    assert client_for(fake).prompt(SESSION, "Add drift history") == 1
    assert fake.bodies(f"/api/session/{SESSION}/prompt") == [
        {"prompt": {"text": "Add drift history"}}
    ]


def test_run_streams_every_step_until_the_session_is_idle(fake: FakeOpenCode) -> None:
    fake.events = [
        (2, "session.next.prompted", {}),
        (3, "session.next.step.started", {}),
        (4, "session.next.tool.called", {"tool": "edit"}),
        (5, "session.next.step.ended", {"finish": "tool-calls"}),
        (6, "session.next.step.started", {}),
        (7, "session.next.step.ended", {"finish": "stop", "cost": 0.01}),
    ]
    fake.active_checks_until_idle = 1  # still busy after the first step

    events = list(client_for(fake).run_events(SESSION, 1))

    assert [(e.id, e.type) for e in events] == [(str(seq), kind) for seq, kind, _ in fake.events]
    assert events[-1].data["finish"] == "stop"


def test_dropped_stream_resumes_after_the_last_sequence(fake: FakeOpenCode) -> None:
    fake.events = [
        (2, "session.next.step.started", {}),
        (3, "session.next.text.ended", {"text": "half"}),
        (4, "session.next.step.ended", {"finish": "stop"}),
    ]
    fake.stream_batches = [3]  # first connection drops after seq 3

    events = list(client_for(fake).run_events(SESSION, 1))

    afters = [r.url.params["after"] for r in fake.requests if r.url.path.endswith("/event")]
    assert [e.id for e in events] == ["2", "3", "4"]
    assert afters == ["1", "3"]


def test_failed_step_ends_the_run(fake: FakeOpenCode) -> None:
    fake.events = [
        (2, "session.next.step.started", {}),
        (3, "session.next.step.failed", {"error": {"message": "HTTP 400"}}),
    ]

    events = list(client_for(fake).run_events(SESSION, 1))

    assert events[-1].type == "session.next.step.failed"


def test_session_idle_without_any_step_is_an_error(fake: FakeOpenCode) -> None:
    fake.events = [(2, "session.next.prompted", {})]

    with pytest.raises(OpenCodeError, match="went idle without running a step"):
        list(client_for(fake).run_events(SESSION, 1))


def test_quiet_stream_while_busy_keeps_waiting(fake: FakeOpenCode) -> None:
    def timeout_then_serve(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/event") and not fake.events:
            fake.events = [(2, "session.next.step.ended", {"finish": "stop"})]
            raise httpx.ReadTimeout("quiet", request=request)
        return fake.handle(request)

    fake.active_checks_until_idle = 1
    client = OpenCodeClient(
        "http://opencode.test", httpx.MockTransport(timeout_then_serve), reconnect_delay=0
    )

    assert [e.id for e in client.run_events(SESSION, 1)] == ["2"]


def test_interrupt(fake: FakeOpenCode) -> None:
    client_for(fake).interrupt(SESSION)

    assert [r.method for r in fake.requests] == ["POST"]


def test_interrupt_of_unknown_session_fails(fake: FakeOpenCode) -> None:
    fake.status_overrides[f"/api/session/{SESSION}/interrupt"] = 404

    with pytest.raises(OpenCodeError):
        client_for(fake).interrupt(SESSION)


def test_usage_records_reported_cost_with_its_source(fake: FakeOpenCode) -> None:
    assert client_for(fake).usage(SESSION) == Usage(
        input_tokens=1200,
        output_tokens=300,
        reasoning_tokens=40,
        cache_read_tokens=900,
        cache_write_tokens=10,
        cost_usd=Decimal("0.0123"),
        cost_source="runtime",
    )


def test_usage_without_reported_cost_has_no_source(fake: FakeOpenCode) -> None:
    fake.session = {"tokens": {"input": 5}}

    usage = client_for(fake).usage(SESSION)

    assert (usage.input_tokens, usage.output_tokens) == (5, 0)
    assert (usage.cost_usd, usage.cost_source) == (None, None)


def test_event_frames_take_their_id_from_the_durable_sequence() -> None:
    event = to_event(None, None, '{"type": "x", "durable": {"seq": 9}, "data": {"k": 1}}')

    assert event is not None and (event.id, event.type, event.data) == ("9", "x", {"k": 1})
    assert to_event("y", "4", "{}") is not None
    assert to_event(None, None, "not json") is None
