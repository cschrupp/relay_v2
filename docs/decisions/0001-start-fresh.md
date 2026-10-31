# 0001 — Start a fresh repository

**Date:** 31 October 2026
**Status:** Accepted

## Context

The first repository, [`cschrupp/relay`](https://github.com/cschrupp/relay),
held about 49,500 lines of source, 36,000 lines of tests and 180,000 lines of
process documentation after five weeks. 92% of its commits touched no source
code, it had 89 branches after a cleanup, and its governed execution loop had
no production caller. Its core purpose, steering agents against drift, was
never built. `LESSONS.md` records the details.

Nothing in it runs end to end and it has no users, so a fresh start loses
little working knowledge, while keeping it would keep pulling work back toward
the old process.

## Decision

- Start Relay again in this repository with a small layered package, drift
  checks in CI from day one, and one-page process docs.
- Port code from the old repository only when the loop needs it, together with
  its tests. Anything never needed stays in the archive.
- Keep the old repository read-only as an archive and as the first test subject
  for drift detection: replaying its history against these checks shows when
  they would have fired.

## Consequences

- History of the first attempt is reached through the old repository, not here.
- The first candidates to port are the `domain` value types, the OpenCode HTTP
  adapter core, the SQLite connection and migration helpers, and later the
  GitHub integration and the constraint-inheritance ideas from `project_state`.
- The onboarding machinery (historical genesis, adoption epochs, origin
  records) is not ported. Onboarding becomes a baseline snapshot of drift
  metrics that new work may not worsen.
