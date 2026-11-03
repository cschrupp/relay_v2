"""The run store: packet runs, their attempts and the developer's decisions, in SQLite.

Writes follow the loop as it happens, each in its own transaction:
`start_run` -> `record_attempt` (when a card is shown) -> `record_decision` (rules,
then the final accept, redirect or reject) -> ... -> `finish_run`. A crash at any point
leaves what was written: a run without `finish_run` is pending, and an attempt without
a final decision is a decision still pending. Both are returned by `pending_runs`.

Derived when read, not stored: the number of attempts, each attempt's outcome and
accept reason (from its final decision), steering time (from a card being shown to the
final decision on it) and the run's total cost.
"""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from relay.domain import (
    Accept,
    DriftCard,
    MakeRule,
    Redirect,
    Reject,
    RunRecord,
    SteerDecision,
    WorkPacket,
)
from relay.domain.steer import Outcome

MIGRATIONS = ("migrations/001_initial.sql", "migrations/002_decided_by.sql")
SCHEMA_VERSION = len(MIGRATIONS)
OUTCOMES: dict[str, Outcome] = {
    "accept": "accepted",
    "redirect": "redirected",
    "reject": "rejected",
}

RunOutcome = Literal["accepted", "rejected", "failed"]
DecidedBy = Literal["developer", "relay"]


class StoreError(RuntimeError):
    """The store refused a write or cannot be opened."""


@dataclass(frozen=True)
class Developer:
    name: str
    email: str


@dataclass(frozen=True)
class StoredDecision:
    decision: SteerDecision
    decided_at: datetime
    by: DecidedBy = "developer"


@dataclass(frozen=True)
class StoredAttempt:
    number: int
    record: RunRecord
    card: DriftCard
    shown_at: datetime
    decisions: tuple[StoredDecision, ...]

    @property
    def steering_seconds(self) -> float | None:
        """Seconds from the card being shown to the final decision; None while pending.

        Zero when Relay made the decision (a cascade step): no one was steering.
        """
        final = [d for d in self.decisions if not isinstance(d.decision, MakeRule)]
        if not final:
            return None
        if final[-1].by == "relay":
            return 0.0
        return (final[-1].decided_at - self.shown_at).total_seconds()


@dataclass(frozen=True)
class StoredRun:
    id: int
    issue: int | None
    goal: str
    base_sha: str
    branch: str
    developer: Developer
    started_at: datetime
    finished_at: datetime | None
    outcome: RunOutcome | None
    pull_request: str | None
    attempts: tuple[StoredAttempt, ...]

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    @property
    def steering_seconds(self) -> float:
        return sum(a.steering_seconds or 0.0 for a in self.attempts)

    @property
    def cost_usd(self) -> Decimal | None:
        """Total agent cost, or None when any attempt's cost is unknown."""
        costs = [attempt.record.cost_usd for attempt in self.attempts]
        known = [cost for cost in costs if cost is not None]
        return sum(known, Decimal(0)) if len(known) == len(costs) else None


def timestamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise StoreError("times must be timezone-aware")
    return moment.isoformat()


def decision_text(decision: SteerDecision) -> str | None:
    if isinstance(decision, Accept):
        return decision.reason
    if isinstance(decision, Redirect):
        return decision.text
    if isinstance(decision, MakeRule):
        return decision.spec
    return None


def decision_from(kind: str, text: str | None) -> SteerDecision:
    if kind == "accept":
        return Accept(reason=text)
    if kind == "redirect":
        return Redirect(text=text or "")
    if kind == "make_rule":
        return MakeRule(spec=text or "")
    return Reject()


class RunStore:
    """One SQLite file; open it, use it, close it."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.migrate()

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    def migrate(self) -> None:
        version: int = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise StoreError(f"store schema {version} is newer than this Relay ({SCHEMA_VERSION})")
        for number, migration in enumerate(MIGRATIONS[version:], start=version + 1):
            script = resources.files("relay.store").joinpath(migration).read_text("utf-8")
            try:
                self.db.executescript(
                    f"BEGIN IMMEDIATE;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;"
                )
            except sqlite3.Error:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise

    def start_run(self, packet: WorkPacket, branch: str, developer: Developer, at: datetime) -> int:
        """Record a new run; `packet.base_sha` must already be the full SHA."""
        with self.transaction() as db:
            cursor = db.execute(
                "INSERT INTO packet_runs (issue, goal, base_sha, branch, developer_name,"
                " developer_email, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    packet.issue,
                    packet.goal,
                    packet.base_sha,
                    branch,
                    developer.name,
                    developer.email,
                    timestamp(at),
                ),
            )
        if cursor.lastrowid is None:
            raise StoreError("the run was not stored")
        return cursor.lastrowid

    def record_attempt(
        self, run_id: int, number: int, record: RunRecord, card: DriftCard, shown_at: datetime
    ) -> None:
        """Record an attempt when its card is shown; its decision follows separately."""
        cost = str(record.cost_usd) if record.cost_usd is not None else None
        with self.transaction() as db:
            db.execute(
                "INSERT INTO attempts (run_id, number, provider, model, role, tier,"
                " input_tokens, output_tokens, cost_usd, cost_source, card, card_shown_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    number,
                    record.provider,
                    record.model,
                    record.role,
                    record.tier,
                    record.input_tokens,
                    record.output_tokens,
                    cost,
                    record.cost_source,
                    card.model_dump_json(),
                    timestamp(shown_at),
                ),
            )

    def record_decision(
        self,
        run_id: int,
        attempt: int,
        decision: SteerDecision,
        decided_at: datetime,
        by: DecidedBy = "developer",
    ) -> None:
        with self.transaction() as db:
            sequence: int = db.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM decisions"
                " WHERE run_id = ? AND attempt = ?",
                (run_id, attempt),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO decisions (run_id, attempt, sequence, kind, text, decided_at,"
                " decided_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    attempt,
                    sequence,
                    decision.kind,
                    decision_text(decision),
                    timestamp(decided_at),
                    by,
                ),
            )

    def finish_run(
        self, run_id: int, outcome: RunOutcome, at: datetime, pull_request: str | None = None
    ) -> None:
        with self.transaction() as db:
            cursor = db.execute(
                "UPDATE packet_runs SET outcome = ?, finished_at = ?, pull_request = ?"
                " WHERE id = ? AND finished_at IS NULL",
                (outcome, timestamp(at), pull_request, run_id),
            )
        if cursor.rowcount != 1:
            raise StoreError(f"run {run_id} does not exist or is already finished")

    def attempts(self, run_id: int) -> tuple[StoredAttempt, ...]:
        rows = self.db.execute(
            "SELECT * FROM attempts WHERE run_id = ? ORDER BY number", (run_id,)
        ).fetchall()
        return tuple(self.attempt_from(row) for row in rows)

    def attempt_from(self, row: Any) -> StoredAttempt:
        decisions = tuple(
            StoredDecision(
                decision_from(d["kind"], d["text"]),
                datetime.fromisoformat(d["decided_at"]),
                d["decided_by"],
            )
            for d in self.db.execute(
                "SELECT kind, text, decided_at, decided_by FROM decisions"
                " WHERE run_id = ? AND attempt = ? ORDER BY sequence",
                (row["run_id"], row["number"]),
            ).fetchall()
        )
        final = [d.decision for d in decisions if not isinstance(d.decision, MakeRule)]
        record = RunRecord(
            provider=row["provider"],
            model=row["model"],
            role=row["role"],
            tier=row["tier"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            cost_usd=Decimal(row["cost_usd"]) if row["cost_usd"] is not None else None,
            cost_source=row["cost_source"],
            outcome=OUTCOMES[final[-1].kind] if final else None,
            accept_reason=final[-1].reason if final and isinstance(final[-1], Accept) else None,
        )
        card = DriftCard.model_validate_json(row["card"])
        shown = datetime.fromisoformat(row["card_shown_at"])
        return StoredAttempt(row["number"], record, card, shown, decisions)

    def run_from(self, row: Any) -> StoredRun:
        finished = row["finished_at"]
        return StoredRun(
            id=row["id"],
            issue=row["issue"],
            goal=row["goal"],
            base_sha=row["base_sha"],
            branch=row["branch"],
            developer=Developer(row["developer_name"], row["developer_email"]),
            started_at=datetime.fromisoformat(row["started_at"]),
            finished_at=datetime.fromisoformat(finished) if finished else None,
            outcome=row["outcome"],
            pull_request=row["pull_request"],
            attempts=self.attempts(row["id"]),
        )

    def run(self, run_id: int) -> StoredRun:
        row = self.db.execute("SELECT * FROM packet_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise StoreError(f"no run {run_id}")
        return self.run_from(row)

    def runs(self, limit: int | None = None) -> list[StoredRun]:
        """Runs newest first; all of them when `limit` is None."""
        rows = self.db.execute(
            "SELECT * FROM packet_runs ORDER BY id DESC LIMIT ?", (-1 if limit is None else limit,)
        ).fetchall()
        return [self.run_from(row) for row in rows]

    def pending_runs(self) -> list[StoredRun]:
        """Runs that never finished, oldest first: what a crash leaves behind."""
        rows = self.db.execute(
            "SELECT * FROM packet_runs WHERE finished_at IS NULL ORDER BY id"
        ).fetchall()
        return [self.run_from(row) for row in rows]
