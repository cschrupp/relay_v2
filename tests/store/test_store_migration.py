import sqlite3
from importlib import resources
from pathlib import Path

from relay.store.runs import SCHEMA_VERSION, RunStore


def test_a_version_1_store_is_migrated_and_keeps_its_decisions(tmp_path: Path) -> None:
    path = tmp_path / "runs.sqlite"
    initial = resources.files("relay.store").joinpath("migrations/001_initial.sql")
    db = sqlite3.connect(path)
    db.executescript(initial.read_text("utf-8") + "\nPRAGMA user_version = 1;")
    db.executescript(
        "INSERT INTO packet_runs (id, goal, base_sha, branch, developer_name, developer_email,"
        f" started_at) VALUES (1, 'g', '{'a' * 40}', 'b', 'Dev', 'dev@example.com',"
        " '2026-11-02T06:00:00+00:00');"
        "INSERT INTO attempts VALUES (1, 1, 'p', 'm', 'implementer', 'cheap', 10, 1, NULL, NULL,"
        ' \'{"base_sha": "' + "a" * 40 + '", "result_sha": "' + "b" * 40 + '",'
        ' "expected_lines": {"source": 1, "tests": 1},'
        ' "actual_lines": {"source": 1, "tests": 1}, "findings": []}\','
        " '2026-11-02T06:00:00+00:00');"
        "INSERT INTO decisions VALUES (1, 1, 1, 'reject', NULL, '2026-11-02T06:00:30+00:00');"
    )
    db.close()

    store = RunStore(path)
    [attempt] = store.run(1).attempts
    version = store.db.execute("PRAGMA user_version").fetchone()[0]
    store.close()

    assert version == SCHEMA_VERSION == 2
    assert [(d.decision.kind, d.by) for d in attempt.decisions] == [("reject", "developer")]
    assert attempt.steering_seconds == 30
