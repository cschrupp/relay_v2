-- Relay run store, schema version 1.
-- One packet run per `relay run`; one attempt per agent turn (a RunRecord and its drift
-- card); every steer decision, including rules made along the way.
-- Times are ISO 8601 UTC text. Costs are decimal text, never floats.

CREATE TABLE packet_runs (
    id              INTEGER PRIMARY KEY,
    issue           INTEGER,
    goal            TEXT    NOT NULL,
    base_sha        TEXT    NOT NULL CHECK (length(base_sha) = 40),
    branch          TEXT    NOT NULL,
    developer_name  TEXT    NOT NULL,
    developer_email TEXT    NOT NULL,
    started_at      TEXT    NOT NULL,
    finished_at     TEXT,
    outcome         TEXT    CHECK (outcome IN ('accepted', 'rejected', 'failed')),
    pull_request    TEXT,
    CHECK ((finished_at IS NULL) = (outcome IS NULL))
);

CREATE TABLE attempts (
    run_id        INTEGER NOT NULL REFERENCES packet_runs (id),
    number        INTEGER NOT NULL CHECK (number >= 1),
    provider      TEXT    NOT NULL,
    model         TEXT    NOT NULL,
    role          TEXT    NOT NULL,
    tier          TEXT    NOT NULL,
    input_tokens  INTEGER NOT NULL CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
    cost_usd      TEXT,
    cost_source   TEXT    CHECK (cost_source IN ('runtime', 'price_table')),
    card          TEXT    NOT NULL,
    card_shown_at TEXT    NOT NULL,
    PRIMARY KEY (run_id, number)
);

CREATE TABLE decisions (
    run_id     INTEGER NOT NULL,
    attempt    INTEGER NOT NULL,
    sequence   INTEGER NOT NULL,
    kind       TEXT    NOT NULL CHECK (kind IN ('accept', 'redirect', 'make_rule', 'reject')),
    text       TEXT,
    decided_at TEXT    NOT NULL,
    PRIMARY KEY (run_id, attempt, sequence),
    FOREIGN KEY (run_id, attempt) REFERENCES attempts (run_id, number)
);
