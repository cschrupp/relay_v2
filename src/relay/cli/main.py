"""The `relay` command."""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from relay.cli.format import format_history, format_hygiene, format_report, format_tidy
from relay.domain import RulesError, parse_rules
from relay.domain.rules import RULES_PATH
from relay.drift.git import GitError, read_optional
from relay.drift.history import DEFAULT_EVERY, build_history
from relay.drift.hygiene import DEFAULT_STALE_DAYS, build_hygiene, pull_requests
from relay.drift.report import DEFAULT_BUDGET, DriftError, build_report
from relay.drift.tidy import apply_action, plan_tidy


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
    add_stale_days(report)
    history = drift_commands.add_parser("history", help="when each drift metric first fired")
    add_measure_arguments(history, "last commit of the history (default: HEAD)")
    history.add_argument(
        "--every", type=positive_int, default=DEFAULT_EVERY, help="sample every Nth commit"
    )
    tidy = commands.add_parser("tidy", help="list branches that can be deleted, and why")
    tidy.add_argument("repo", type=Path, help="path to a git repository")
    tidy.add_argument("--apply", action="store_true", help="archive and delete them")
    add_stale_days(tidy)
    return parser


def add_stale_days(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--stale-days",
        type=positive_int,
        default=DEFAULT_STALE_DAYS,
        help="branches with no commits for this many days are stale",
    )


def run_report(args: argparse.Namespace) -> str:
    report = build_report(args.repo, args.rev, args.root, args.budget)
    rules = parse_rules(read_optional(args.repo, report.commit, RULES_PATH))
    prs = pull_requests(args.repo)
    hygiene = build_hygiene(args.repo, rules, prs, datetime.now(UTC), args.stale_days)
    if args.json:
        return json.dumps({**asdict(report), "hygiene": asdict(hygiene)}, indent=2)
    return f"{format_report(report)}\n\n{format_hygiene(hygiene)}"


def run_tidy(args: argparse.Namespace) -> str:
    prs = pull_requests(args.repo)
    actions = plan_tidy(args.repo, prs, datetime.now(UTC), args.stale_days)
    lines = format_tidy(actions, prs is not None, args.apply)
    if args.apply:
        for action in actions:
            try:
                lines.append(f"  {apply_action(args.repo, action)}")
            except GitError as error:
                lines.append(f"Stopped: {error}")
                break
    return "\n".join(lines)


def run(args: argparse.Namespace) -> str:
    """Run the parsed command and return its output text."""
    if args.command == "tidy":
        return run_tidy(args)
    if args.drift_command == "history":
        history = build_history(args.repo, args.rev, args.root, args.budget, args.every)
        return json.dumps(asdict(history), indent=2) if args.json else format_history(history)
    return run_report(args)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output = run(args)
    except (GitError, DriftError, RulesError) as error:
        print(f"relay: {error}", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
