import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from relay.domain import (
    Accept,
    DriftCard,
    DriftFinding,
    LineEstimate,
    MakeRule,
    NetLines,
    Redirect,
    Reject,
    RunRecord,
    WorkPacket,
)
from relay.store.runs import Developer, RunStore, StoreError

BASE = "d593b9aa4fabb37ccebfa9ccccdca4c16fc78844"
T0 = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)
DEVELOPER = Developer("Dev", "dev@example.com")
PACKET = WorkPacket(
    goal="Add relay --version",
    base_sha=BASE,
    allowed_paths=("src/relay/cli/main.py",),
    expected_lines=LineEstimate(source=10, tests=15),
    acceptance_commands=("uv run pytest",),
    token_budget=200000,
    role="implementer",
    tier="cheap",
    issue=21,
)
CARD = DriftCard(
    base_sha=BASE,
    result_sha="f9cdf904a612" + "0" * 28,
    expected_lines=LineEstimate(source=10, tests=15),
    actual_lines=NetLines(source=6, tests=13),
    findings=(DriftFinding(kind="net_lines", message="source +6"),),
)


def record(cost: str | None = "0.003679504", source: str | None = "runtime") -> RunRecord:
    return RunRecord.model_validate(
        {
            "provider": "openrouter",
            "model": "deepseek/deepseek-v4.1-flash",
            "role": "implementer",
            "tier": "cheap",
            "input_tokens": 23056,
            "output_tokens": 1826,
            "cost_usd": cost,
            "cost_source": source,
        }
    )


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    return RunStore(tmp_path / "relay" / "runs.sqlite3")


def test_a_run_is_stored_and_read_back(store: RunStore) -> None:
    run_id = store.start_run(PACKET, "relay/21-add-relay-version", DEVELOPER, T0)

    run = store.run(run_id)

    assert (run.issue, run.goal, run.base_sha, run.branch) == (
        21,
        "Add relay --version",
        BASE,
        "relay/21-add-relay-version",
    )
    assert (run.developer, run.started_at, run.finished_at, run.outcome) == (
        DEVELOPER,
        T0,
        None,
        None,
    )
    assert run.attempts == ()


def test_attempt_keeps_provider_cost_source_and_card(store: RunStore) -> None:
    run_id = store.start_run(PACKET, "b", DEVELOPER, T0)
    store.record_attempt(run_id, 1, record(), CARD, T0)

    [attempt] = store.run(run_id).attempts

    assert attempt.record == record()
    assert (attempt.record.provider, attempt.record.cost_source) == ("openrouter", "runtime")
    assert attempt.record.cost_usd == Decimal("0.003679504")
    assert attempt.card == CARD
    assert attempt.shown_at == T0


def test_decisions_steering_time_and_outcomes(store: RunStore) -> None:
    run_id = store.start_run(PACKET, "b", DEVELOPER, T0)
    store.record_attempt(run_id, 1, record(), CARD, T0)
    store.record_decision(run_id, 1, MakeRule(spec="keep cli thin"), T0 + timedelta(seconds=20))
    store.record_decision(run_id, 1, Redirect(text="smaller"), T0 + timedelta(seconds=65))
    second = T0 + timedelta(minutes=3)
    store.record_attempt(run_id, 2, record("0.001"), CARD, second)
    store.record_decision(
        run_id, 2, Accept(reason="approved, see #7"), second + timedelta(seconds=10)
    )
    store.finish_run(
        run_id, "accepted", second + timedelta(seconds=12), "https://github.test/pr/24"
    )

    run = store.run(run_id)

    first, last = run.attempts
    assert [d.decision for d in first.decisions] == [
        MakeRule(spec="keep cli thin"),
        Redirect(text="smaller"),
    ]
    assert (first.record.outcome, first.steering_seconds) == ("redirected", 65.0)
    assert (last.record.outcome, last.record.accept_reason) == ("accepted", "approved, see #7")
    assert (run.attempt_count, run.steering_seconds) == (2, 75.0)
    assert run.cost_usd == Decimal("0.004679504")
    assert (run.outcome, run.pull_request, run.finished_at) == (
        "accepted",
        "https://github.test/pr/24",
        second + timedelta(seconds=12),
    )
    assert store.pending_runs() == []


def test_rejected_run_and_unknown_cost(store: RunStore) -> None:
    run_id = store.start_run(PACKET, "b", DEVELOPER, T0)
    store.record_attempt(run_id, 1, record(cost=None, source=None), CARD, T0)
    store.record_decision(run_id, 1, Reject(), T0 + timedelta(seconds=5))
    store.finish_run(run_id, "rejected", T0 + timedelta(seconds=6))

    run = store.run(run_id)

    assert run.attempts[0].record.outcome == "rejected"
    assert run.attempts[0].record.cost_source is None
    assert run.cost_usd is None


def test_crash_before_the_decision_leaves_a_pending_run(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite3"
    crashed = RunStore(path)
    run_id = crashed.start_run(PACKET, "relay/21-add-relay-version", DEVELOPER, T0)
    crashed.record_attempt(run_id, 1, record(), CARD, T0)
    crashed.db.close()  # the process dies here: no decision, no finish

    reopened = RunStore(path)
    [pending] = reopened.pending_runs()

    assert (pending.id, pending.branch, pending.base_sha) == (
        run_id,
        "relay/21-add-relay-version",
        BASE,
    )
    [attempt] = pending.attempts
    assert (attempt.record.outcome, attempt.steering_seconds, attempt.decisions) == (None, None, ())

    reopened.record_decision(run_id, 1, Reject(), T0 + timedelta(hours=1))
    reopened.finish_run(run_id, "failed", T0 + timedelta(hours=1))
    assert reopened.pending_runs() == []


def test_a_run_finishes_once(store: RunStore) -> None:
    run_id = store.start_run(PACKET, "b", DEVELOPER, T0)
    store.finish_run(run_id, "rejected", T0)

    with pytest.raises(StoreError, match="already finished"):
        store.finish_run(run_id, "accepted", T0)
    with pytest.raises(StoreError, match="does not exist"):
        store.finish_run(999, "accepted", T0)


def test_invalid_writes_are_refused_and_rolled_back(store: RunStore) -> None:
    short = PACKET.model_copy(update={"base_sha": "d593b9a"})

    with pytest.raises(sqlite3.IntegrityError):
        store.start_run(short, "b", DEVELOPER, T0)
    with pytest.raises(StoreError, match="timezone-aware"):
        store.start_run(PACKET, "b", DEVELOPER, datetime(2026, 11, 2))
    run_id = store.start_run(PACKET, "b", DEVELOPER, T0)
    with pytest.raises(sqlite3.IntegrityError):
        store.record_decision(run_id, 1, Reject(), T0)

    assert [run.id for run in store.pending_runs()] == [run_id]
    assert not store.db.in_transaction


def test_schema_is_created_once_and_newer_schemas_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite3"
    RunStore(path).close()
    RunStore(path).close()
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version = 2")
    db.close()

    with pytest.raises(StoreError, match="newer than this Relay"):
        RunStore(path)
