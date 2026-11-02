"""Human-readable rendering of drift reports and histories."""

from relay.drift.history import DriftHistory
from relay.drift.hygiene import Hygiene
from relay.drift.report import DriftReport
from relay.drift.tidy import TidyAction

SHOWN_FUNCTIONS = 10
SUBJECT_WIDTH = 60


def format_report(report: DriftReport) -> str:
    """Render a report as a short human-readable table."""
    lines = [f"{report.root} at {report.commit[:12]} ({report.date[:10]})", ""]
    lines.append(f"Import cycles between top-level packages: {len(report.cycles)}")
    lines += [f"  {len(cycle):>3} packages: {', '.join(cycle)}" for cycle in report.cycles]
    lines += ["", f"Functions over {report.budget} lines: {len(report.oversized)}"]
    for found in report.oversized[:SHOWN_FUNCTIONS]:
        lines.append(f"  {found.lines:>5}  {found.path}:{found.line}  {found.name}")
    if len(report.oversized) > SHOWN_FUNCTIONS:
        hidden = len(report.oversized) - SHOWN_FUNCTIONS
        lines.append(f"  ... and {hidden} more (--json lists all)")
    lines += [
        "",
        f"Source: {report.source_lines:,} lines in {report.source_files} files",
        f"Tests:  {report.test_lines:,} lines in {report.test_files} files",
        "Largest files:",
    ]
    lines += [f"  {size.lines:>6,}  {size.path}" for size in report.largest_files]
    if report.unparsable:
        lines += ["", f"Could not parse: {', '.join(report.unparsable)}"]
    if report.skipped_symlinks:
        lines += ["", f"Skipped symlinks: {', '.join(report.skipped_symlinks)}"]
    return "\n".join(lines)


def format_history(history: DriftHistory) -> str:
    """Render the first firing of each metric as a table, oldest first."""
    lines = [
        f"{history.root}: {history.commits} first-parent commits up to {history.rev}, "
        f"sampled every {history.every}, budget {history.budget} lines",
        "",
    ]
    for number, cycle in enumerate(history.final_cycles, start=1):
        lines.append(f"Final cycle {number}: {', '.join(cycle)}")
    width = max((len(firing.metric) for firing in history.firings), default=0)
    lines += ["", f"{'First fired':<{width}}  {'#':>5}  {'Date':<10}  {'Commit':<10}  Subject"]
    for firing in sorted(history.firings, key=lambda firing: (firing.position, firing.metric)):
        subject = firing.subject[:SUBJECT_WIDTH]
        lines.append(
            f"{firing.metric:<{width}}  {firing.position:>5}  {firing.date[:10]}  "
            f"{firing.commit[:10]}  {subject}"
        )
    if not history.firings:
        lines.append("Nothing fired.")
    lines += ["", f"# is the position on first-parent history (0 = first of {history.commits})."]
    lines.append("--json adds the sampled series of counts.")
    return "\n".join(lines)


def format_hygiene(hygiene: Hygiene) -> str:
    """Render the branch hygiene section."""
    default = hygiene.default_branch
    unknown = "unknown (no PR data from gh)"
    budget = "unknown" if hygiene.budget is None else str(hygiene.budget)
    without_pr = hygiene.without_open_pr
    prunable = sum(tree.prunable for tree in hygiene.worktrees)
    lines = [
        f"Branch hygiene (default branch {default})",
        f"  Branches besides {default}: {hygiene.branches} "
        f"({hygiene.local_branches} local refs, {hygiene.remote_branches} remote refs)",
        f"  Budget: {budget}; open PRs: "
        + (unknown if hygiene.open_pull_requests is None else str(hygiene.open_pull_requests)),
        f"  Merged but not deleted: {len(hygiene.merged)}",
        f"  Without an open PR: {unknown if without_pr is None else len(without_pr)}",
        f"  No commits in {hygiene.stale_days} days: {len(hygiene.stale)}",
        f"  Extra worktrees: {len(hygiene.worktrees)} ({prunable} prunable)",
    ]
    lines += [f"  Drift: {finding.message}" for finding in hygiene.findings]
    return "\n".join(lines)


def format_tidy(actions: list[TidyAction], prs_known: bool, applying: bool) -> list[str]:
    """Render the tidy plan, one line per ref."""
    verb = "Deleting" if applying else "Dry run:"
    lines = [f"{verb} {len(actions)} branch refs can go"]
    width = max((len(action.ref) for action in actions), default=0)
    for action in actions:
        archived = f"; archived as archive/{action.name} first" if action.archive else ""
        lines.append(f"  {action.ref:<{width}}  {action.reason}{archived}")
    if not prs_known:
        lines.append("PR state unknown (no PR data from gh): only merged branches are listed.")
    if not applying and actions:
        lines.append("Nothing was changed. Re-run with --apply to delete.")
    return lines
