# Relay

Relay keeps agent-built software faithful to its developer's design.

Left alone, coding agents drift: architecture bends toward whatever the current
prompt asks for, code bloats, reuse and optimization disappear, and good
practice erodes. No initial prompt can describe a project completely, so
divergence cannot be prevented up front. It can only be bounded by closing the
loop.

Relay closes that loop:

1. **Short work packets.** An agent (OpenCode first) works on one bounded task.
2. **A measured stop.** When it stops, Relay computes a *drift card* from the
   diff and the project's executable rules: layer violations and new cycles,
   functions over budget, net lines against the expected size, duplication,
   new dependencies, edited tests, files outside scope, conflicts with recorded
   decisions.
3. **One-action re-steering.** The developer accepts, redirects, or says "make
   this a rule".
4. **A ratchet.** Wherever possible, a correction becomes an executable check,
   so the specification grows out of steering and direction converges over time.

Relay also routes work to the right model: stronger models for architecture and
review, cheaper models for bounded implementation. It escalates only when the
drift and acceptance checks say the cheaper result is not good enough, and it
reports cost per accepted change.

## Status

Nothing in the loop is built yet. This repository starts from the lessons of
the first attempt, [`cschrupp/relay`](https://github.com/cschrupp/relay), which
is kept as an archive and as the first test subject for drift detection.

See:

- [`LESSONS.md`](LESSONS.md) — what the first attempt taught, and why this one starts small
- [`DEVELOPMENT.md`](DEVELOPMENT.md) — how work happens in this repository
- [`AGENTS.md`](AGENTS.md) — instructions for coding agents
- [`docs/decisions/`](docs/decisions/) — one record per real architectural decision

## Development

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --group dev
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run lint-imports
uv run python tools/check_function_size.py
uv run pytest
```
