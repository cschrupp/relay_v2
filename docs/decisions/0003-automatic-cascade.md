# 0003 — Relay retries and escalates on its own, within limits

**Date:** 3 November 2026
**Status:** Accepted

## Context

Steering is the developer's job, and until now every drift card went to them. But a
card with failed acceptance checks or blocking findings is one a machine can judge:
the answer is always "not yet". Showing those cards to the developer spends their
time, which `relay runs` now counts as part of the cost per accepted change. Routing
(#10) also needs a rule for when cheap work escalates to a strong model.

## Decision

When an attempt fails an acceptance check or has a blocking finding, Relay retries
once on the same model with the card as feedback. If the retry fails too, Relay
escalates once from the cheap tier to the strong one, in a new session on the same
branch. Then the card goes to the developer.

- Warnings never trigger an automatic step; they always go to the developer.
- No automatic step starts once the packet's token budget is spent. Each session is
  interrupted when its own totals (`GET /session/{id}`, read after every step) go over
  what is left of the budget.
- The developer sees every card. Each automatic step is stored as a decision made by
  Relay (`decided_by = 'relay'`, schema version 2), and it is not counted as steering
  time.
- `relay run --no-cascade` turns the cascade off, so every card goes to the
  developer. This is for measuring the cascade against plain steering.

## Consequences

- Cards a machine can judge no longer cost the developer's time. Retries and
  escalations cost tokens instead, and both are recorded per attempt with their tier.
- A packet can span two sessions and two models; its pull request reports the total
  over all of them.
- The budget can be exceeded by at most one step, because OpenCode reports totals
  only after a step ends.
