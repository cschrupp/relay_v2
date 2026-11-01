"""The `relay` command."""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from relay.cli.format import format_history, format_report
from relay.drift.git import GitError
from relay.drift.history import DEFAULT_EVERY, build_history
from relay.drift.report import DEFAULT_BUDGET, DriftError, build_report


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def add_measure_arguments(parser: argparse.ArgumentParser, rev_help: str) -> None:
    parser.add_argument("repo", type=Path, help="path to a git repository")
    parser.add_argument("--rev", default="HEAD", help=rev_help)
    parser.add_argument("--root", help="package directory to measure, e.g. src/pkg")
    parser.add_argument("--budget", type=positive_int, default=DEFAULT_BUDGET)
    parser.add_argument("--json", action="store_true", help="print JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="relay", description="Steer coding agents against drift.")
    commands = parser.add_subparsers(dest="command", required=True)
    drift = commands.add_parser("drift", help="measure structural drift")
    drift_commands = drift.add_subparsers(dest="drift_command", required=True)
    report = drift_commands.add_parser("report", help="drift metrics at one commit")
    add_measure_arguments(report, "commit to measure (default: HEAD)")
    history = drift_commands.add_parser("history", help="when each drift metric first fired")
    add_measure_arguments(history, "last commit of the history (default: HEAD)")
    history.add_argument(
        "--every", type=positive_int, default=DEFAULT_EVERY, help="sample every Nth commit"
    )
    return parser


def run(args: argparse.Namespace) -> str:
    """Run the parsed command and return its output text."""
    if args.drift_command == "history":
        history = build_history(args.repo, args.rev, args.root, args.budget, args.every)
        return json.dumps(asdict(history), indent=2) if args.json else format_history(history)
    report = build_report(args.repo, args.rev, args.root, args.budget)
    return json.dumps(asdict(report), indent=2) if args.json else format_report(report)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output = run(args)
    except (GitError, DriftError) as error:
        print(f"relay: {error}", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
