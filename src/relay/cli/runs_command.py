"""`relay runs`: recent runs from the repository's run store, with totals.

Totals cover every run in the store, not only the listed ones. Cost and steering time
per accepted run divide everything spent (including rejected and failed runs) by the
number of accepted runs: what one accepted change really cost.
"""

import argparse
from decimal import Decimal
from pathlib import Path

from relay.drift.git import GitError
from relay.loop.record import store_path
from relay.store.runs import RunStore, StoredRun, StoreError

DEFAULT_LIMIT = 20
HEADER = f"{'run':>4}  {'issue':<6} {'outcome':<9} {'att':>3}  {'cost':>9}  {'steer':>7}  model"


def add_runs_arguments(runs: argparse.ArgumentParser) -> None:
    runs.add_argument("--repo", type=Path, default=Path("."), help="repository (default: .)")
    runs.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="runs to list")


def duration(seconds: float) -> str:
    whole = round(seconds)
    return f"{whole // 60}m{whole % 60:02d}s"


def money(cost: Decimal | None) -> str:
    return "unknown" if cost is None else f"${cost:.4f}"


def run_line(run: StoredRun) -> str:
    issue = f"#{run.issue}" if run.issue is not None else "-"
    models = ", ".join(dict.fromkeys(f"{a.record.provider}/{a.record.model}" for a in run.attempts))
    return (
        f"{run.id:>4}  {issue:<6} {run.outcome or 'pending':<9} {run.attempt_count:>3}  "
        f"{money(run.cost_usd):>9}  {duration(run.steering_seconds):>7}  {models or '-'}"
    )


def totals_line(runs: list[StoredRun]) -> str:
    accepted = sum(1 for run in runs if run.outcome == "accepted")
    known = [run.cost_usd for run in runs if run.cost_usd is not None]
    cost = sum(known, Decimal(0))
    unknown = len(runs) - len(known)
    line = f"All {len(runs)} runs: {accepted} accepted, total cost {money(cost)}"
    if unknown:
        line += f" ({unknown} with unknown cost, not included)"
    if accepted:
        steering = sum(run.steering_seconds for run in runs)
        line += (
            f"; per accepted run: {money(cost / accepted)}"
            f" and {duration(steering / accepted)} steering"
        )
    return line


def format_runs(listed: list[StoredRun], every: list[StoredRun]) -> str:
    if not every:
        return "No runs recorded yet."
    return "\n".join([HEADER, *(run_line(run) for run in listed), "", totals_line(every)])


def runs_command(args: argparse.Namespace) -> tuple[str, int]:
    if args.limit < 1:
        return "relay runs: --limit must be at least 1", 2
    try:
        path = store_path(args.repo)
    except GitError as error:
        return f"relay runs: {error}", 2
    if not path.exists():
        return f"No runs recorded yet.\nRun store: {path}", 0
    try:
        store = RunStore(path)
    except StoreError as error:
        return f"relay runs: {error}\nRun store: {path}", 2
    try:
        text = format_runs(store.runs(args.limit), store.runs())
    finally:
        store.close()
    return f"{text}\nRun store: {path}", 0
