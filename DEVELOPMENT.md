# How work happens here

One page. If this file grows past one page, the process is drifting.

## The flow

```text
issue  ->  branch  ->  pull request  ->  CI  ->  human review  ->  squash merge
```

- `main` is protected: changes arrive only through pull requests with green CI.
- One short-lived branch per pull request. No branches per role, review or approval.
- Head branches are deleted after merge.

## Human gates

| Gate | When | Where it is recorded |
| --- | --- | --- |
| HA-1 — direction | Before non-trivial work starts | The issue: goal, scope, expected size, constraints |
| HA-2 — acceptance | When the work is done | The pull request review and merge |
| HA-X — exceptional | Only for irreversible effects: deploys, credentials, deleting data, publishing, spending | A comment on the issue or PR before the action |

Everything between HA-1 and HA-2 belongs to whoever does the work, human or
agent: planning, implementation, tests, fixes, self-review and rework requested
by a reviewer. None of it needs a separate approval or record.

## What gets written down

- **Decisions:** one short record in `docs/decisions/` per real architectural
  decision. Not per task, review or step.
- **Lessons:** `LESSONS.md`, kept current. Edit it when you learn something.
- **Status:** issues and pull requests. Never in `README.md` or `AGENTS.md`.

## Rules over prose

When a review finds drift, prefer turning the correction into a check that CI
runs (an import contract, a size budget, a test) over writing a guideline. A
guideline that matters and can be checked should be checked.

## Budget

Process work (docs about process, records, tooling for the process itself)
should stay under about 15% of commits. CI reports the share on every run. If it
rises above that for two weeks, stop and ask whether the product is moving.
