-- Relay run store, schema version 2.
-- Who made each decision: the developer, or Relay itself when the cascade retries or
-- escalates on failed acceptance checks or blocking findings (#10). Relay's decisions
-- are not steering time.

ALTER TABLE decisions ADD COLUMN decided_by TEXT NOT NULL DEFAULT 'developer'
    CHECK (decided_by IN ('developer', 'relay'));
