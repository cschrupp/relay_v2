"""Human-readable rendering of drift reports and histories."""

from relay.drift.history import DriftHistory
from relay.drift.report import DriftReport

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
