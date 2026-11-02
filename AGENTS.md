# Instructions for coding agents

Read `README.md` (what Relay is for), `DEVELOPMENT.md` (how work happens) and
`LESSONS.md` (what went wrong before) before substantive work.

Current status and the task at hand live in the issue or pull request you were
given, never in this file.

## Scope

- Work only on the issue you were given. If correct completion needs more,
  stop and propose the extra work in your report instead of doing it.
- Own your internal plan: inspect, implement, test, fix, self-review, and keep
  going until done, blocked or out of budget. Do not stop for approval after
  routine steps.
- Stop and report when the task needs a new dependency, a change to the
  toolchain, a change to `.importlinter` or the size budget, or a decision the
  issue does not settle.
- Never merge pull requests or push to main; the human merges.
- Stage files by explicit path; never `git add -A` or `git add .`.

## Architecture

Packages live under `src/relay/` in layers. Higher layers may import lower ones,
never the reverse:

```text
cli
loop
drift | runtime | store      (independent of each other)
domain
```

`uv run lint-imports` enforces this. Do not edit the contract to make it pass;
report the conflict instead.

## Code

- Explicit control flow, small direct functions, typed boundaries.
- Functions stay within the budget checked by `tools/check_function_size.py`.
- No abstraction without a present need: no factories for one construction
  path, no registries for fixed sets, no plugin systems, no base classes
  without a shared invariant, no config switches for hypothetical cases.
- Use `raise`, not `assert`, for anything that guards correctness.
- Never edit existing tests to make failing code pass. If a deliberate change I
  approved requires a test change, change only the minimum, keep the original
  assertion's intent, and list each edited test under "Test changes" in the PR.
  If a test looks wrong, stop and explain why.
- Never commit secrets.

## Checks

Run all of these before reporting work as done:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run lint-imports
uv run python tools/check_function_size.py
uv run pytest
```

Passing checks are evidence, not acceptance. A human accepts work by merging
the pull request.

## Docs

- Do not add status text, progress logs or review records to the repository.
- Record a real architectural decision as a short file in `docs/decisions/`.
- Add to `LESSONS.md` when you learn something the next agent should know.
