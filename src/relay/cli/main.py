"""The `relay` command."""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from relay.drift.git import GitError
from relay.drift.report import DEFAULT_BUDGET, DriftError, DriftReport, build_report

SHOWN_FUNCTIONS = 10


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="relay", description="Steer coding agents against drift.")
    commands = parser.add_subparsers(dest="command", required=True)
    drift = commands.add_parser("drift", help="measure structural drift")
    drift_commands = drift.add_subparsers(dest="drift_command", required=True)
    report = drift_commands.add_parser("report", help="drift metrics at one commit")
    report.add_argument("repo", type=Path, help="path to a git repository")
    report.add_argument("--rev", default="HEAD", help="commit to measure (default: HEAD)")
    report.add_argument("--root", help="package directory to measure, e.g. src/pkg")
    report.add_argument("--budget", type=positive_int, default=DEFAULT_BUDGET)
    report.add_argument("--json", action="store_true", help="print the report as JSON")
    return parser


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
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = build_report(args.repo, args.rev, args.root, args.budget)
    except (GitError, DriftError) as error:
        print(f"relay: {error}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(report), indent=2) if args.json else format_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
