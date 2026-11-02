from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fake_opencode import IDLE, SESSION, STEP_START, FakeOpenCode

from relay.runtime.opencode import OpenCodeClient, OpenCodeError, SessionSpec, Usage, to_event

SPEC = SessionSpec(Path("/work/repo"), "implementer", "openrouter", "deepseek/deepseek-v4.1-flash")


@pytest.fixture
def fake() -> FakeOpenCode:
    return FakeOpenCode()


def client_for(fake: FakeOpenCode) -> OpenCodeClient:
    return OpenCodeClient("http://opencode.test", fake.transport(), idle_check_seconds=0.1)


def started(fake: FakeOpenCode) -> OpenCodeClient:
    client = client_for(fake)
    client.create_session(SPEC)
    return client


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

    assert fake.bodies("/session") == [
        {
            "agent": "implementer",
            "model": {"id": "deepseek/deepseek-v4.1-flash", "providerID": "openrouter"},
        },
        {"agent": "reviewer", "model": {"id": "gpt-6", "providerID": "openai"}},
    ]
    directories = {r.url.params["directory"] for r in fake.requests}
    assert directories == {"/work/repo"}


def test_unknown_agent_is_rejected_before_creating_a_session(fake: FakeOpenCode) -> None:
    with pytest.raises(OpenCodeError, match="no agent 'implementr'.*implementer"):
        client_for(fake).create_session(SessionSpec(Path("/work/repo"), "implementr", "p", "m"))

    assert fake.bodies("/session") == []


@pytest.mark.parametrize(
    "override",
    [
        {"model": {"id": "other-model", "providerID": "openrouter"}},
        {"directory": "/elsewhere"},
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
    fake.status_overrides["/session"] = 401

    with pytest.raises(OpenCodeError) as error:
        client_for(fake).create_session(SPEC)

    assert error.value.status == 401


def test_prompt_is_sent_after_subscribing_with_agent_and_model(fake: FakeOpenCode) -> None:
    list(started(fake).run(SESSION, "Add drift history"))

    paths = fake.paths()
    assert paths.index("GET /event") < paths.index(f"POST /session/{SESSION}/prompt_async")
    assert fake.bodies(f"/session/{SESSION}/prompt_async") == [
        {
            "agent": "implementer",
            "model": {"providerID": "openrouter", "modelID": "deepseek/deepseek-v4.1-flash"},
            "parts": [{"type": "text", "text": "Add drift history"}],
        }
    ]


def test_run_streams_every_event_until_the_session_is_idle(fake: FakeOpenCode) -> None:
    tool = (
        "message.part.updated",
        {"part": {"type": "tool", "tool": "edit", "state": {"status": "completed"}}},
    )
    other = ("message.part.updated", {"sessionID": "ses_other"})
    fake.event_batches = [[STEP_START, tool, other, IDLE, ("session.status", {})]]

    events = list(started(fake).run(SESSION, "go"))

    assert [e.type for e in events] == [
        "message.part.updated",
        "message.part.updated",
        "session.idle",
    ]


def test_dropped_stream_reconnects_while_busy(fake: FakeOpenCode) -> None:
    fake.event_batches = [[STEP_START], [IDLE]]
    fake.busy_checks = 1

    events = list(started(fake).run(SESSION, "go"))

    assert [e.type for e in events] == ["message.part.updated", "session.idle"]
    assert fake.paths().count("GET /event") == 2
    assert len(fake.bodies(f"/session/{SESSION}/prompt_async")) == 1


def test_missed_idle_is_found_through_the_session_status(fake: FakeOpenCode) -> None:
    fake.event_batches = [[STEP_START]]

    events = list(started(fake).run(SESSION, "go"))

    assert [e.type for e in events] == ["message.part.updated"]


def test_error_after_a_step_ends_the_run_with_the_error_event(fake: FakeOpenCode) -> None:
    error = ("session.error", {"error": {"name": "UnknownError", "data": {"message": "HTTP 400"}}})
    fake.event_batches = [[STEP_START, error, IDLE]]

    events = list(started(fake).run(SESSION, "go"))

    assert [e.type for e in events][-2:] == ["session.error", "session.idle"]


def test_session_idle_without_any_step_is_an_error_with_checks(fake: FakeOpenCode) -> None:
    error = (
        "session.error",
        {"error": {"name": "UnknownError", "data": {"message": "Model unavailable"}}},
    )
    fake.event_batches = [[error, IDLE]]

    with pytest.raises(OpenCodeError) as raised:
        list(started(fake).run(SESSION, "go"))

    message = str(raised.value)
    assert (
        "without running a step with openrouter/deepseek/deepseek-v4.1-flash: Model unavailable"
        in message
    )
    assert 'opencode run --model openrouter/deepseek/deepseek-v4.1-flash "reply with ok"' in message
    assert "opencode serve --print-logs" in message
    assert "`opencode models openrouter` lists deepseek/deepseek-v4.1-flash" in message


def test_quiet_stream_while_busy_keeps_waiting(fake: FakeOpenCode) -> None:
    def timeout_once(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/event" and fake.paths().count("GET /event") == 0:
            fake.requests.append(request)
            raise httpx.ReadTimeout("quiet", request=request)
        return fake.handle(request)

    fake.busy_checks = 1
    client = OpenCodeClient("http://opencode.test", httpx.MockTransport(timeout_once))
    client.create_session(SPEC)

    assert [e.type for e in client.run(SESSION, "go")] == ["message.part.updated", "session.idle"]


def test_runs_need_a_session_from_this_client(fake: FakeOpenCode) -> None:
    with pytest.raises(OpenCodeError, match="not created by this client"):
        list(client_for(fake).run("ses_unknown", "go"))


def test_interrupt(fake: FakeOpenCode) -> None:
    started(fake).interrupt(SESSION)

    assert fake.paths()[-1] == f"POST /session/{SESSION}/abort"


def test_interrupt_of_unknown_session_fails(fake: FakeOpenCode) -> None:
    fake.status_overrides[f"/session/{SESSION}/abort"] = 404

    with pytest.raises(OpenCodeError):
        started(fake).interrupt(SESSION)


def test_usage_records_reported_cost_with_its_source(fake: FakeOpenCode) -> None:
    assert started(fake).usage(SESSION) == Usage(
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

    usage = started(fake).usage(SESSION)

    assert (usage.input_tokens, usage.output_tokens) == (5, 0)
    assert (usage.cost_usd, usage.cost_source) == (None, None)


def test_event_frames_decode_type_and_properties() -> None:
    event = to_event('{"type": "session.idle", "properties": {"sessionID": "ses_1"}}')

    assert event is not None and (event.type, event.data) == (
        "session.idle",
        {"sessionID": "ses_1"},
    )
    assert to_event('{"properties": {}}') is None
    assert to_event("not json") is None
