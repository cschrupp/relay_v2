"""Replay first-parent history and find when each drift metric first fired.

Every Nth commit (and the last) is measured. When a metric fires at a sample, the
commits between it and the previous clean sample are bisected to find the first
commit where it fires. Bisection assumes the metric does not flicker inside that
interval; with `every=1` no bisection happens and the answer is exact.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from relay.drift.git import Commit, first_parent_commits
from relay.drift.report import DEFAULT_BUDGET, DriftError, DriftReport, build_report

DEFAULT_EVERY = 10

Predicate = Callable[[DriftReport], bool]


@dataclass(frozen=True)
class FirstFiring:
    metric: str
    commit: str
    date: str
    subject: str
    position: int


@dataclass(frozen=True)
class Sample:
    commit: str
    date: str
    cycles: int
    largest_cycle: int
    oversized: int
    source_lines: int
    test_lines: int


@dataclass(frozen=True)
class DriftHistory:
    rev: str
    root: str
    budget: int
    every: int
    commits: int
    final_cycles: tuple[tuple[str, ...], ...]
    firings: tuple[FirstFiring, ...]
    series: tuple[Sample, ...]


class Replay:
    """Measures commits of one history on demand, each at most once."""

    def __init__(self, repo: Path, root: str, budget: int) -> None:
        self.repo = repo
        self.root = root
        self.budget = budget
        self.reports: dict[str, DriftReport | None] = {}

    def report(self, commit: Commit) -> DriftReport | None:
        """Return the report at commit, or None when the root has no Python files yet."""
        if commit.sha not in self.reports:
            try:
                self.reports[commit.sha] = build_report(
                    self.repo, commit.sha, self.root, self.budget
                )
            except DriftError:
                self.reports[commit.sha] = None
        return self.reports[commit.sha]

    def fires(self, commit: Commit, predicate: Predicate) -> bool:
        report = self.report(commit)
        return report is not None and predicate(report)


def cycle_within(members: frozenset[str]) -> Predicate:
    return lambda report: any(members.issuperset(cycle) for cycle in report.cycles)


def package_in_cycle(package: str) -> Predicate:
    return lambda report: any(package in cycle for cycle in report.cycles)


def metrics_for(final: DriftReport) -> list[tuple[str, Predicate]]:
    """The metrics to trace back, derived from what fires at the final commit."""
    metrics: list[tuple[str, Predicate]] = [
        ("any import cycle", lambda report: bool(report.cycles)),
        (f"any function over {final.budget} lines", lambda report: bool(report.oversized)),
    ]
    for number, cycle in enumerate(final.cycles, start=1):
        label = f"cycle inside final cycle {number} ({len(cycle)} packages)"
        metrics.append((label, cycle_within(frozenset(cycle))))
        metrics += [(f"{package} in a cycle", package_in_cycle(package)) for package in cycle]
    return metrics


def sample_positions(count: int, every: int) -> list[int]:
    positions = list(range(0, count, every))
    if positions[-1] != count - 1:
        positions.append(count - 1)
    return positions


def first_firing(
    replay: Replay, commits: list[Commit], samples: list[int], predicate: Predicate
) -> int | None:
    """Return the position of the first commit where predicate fires, or None."""
    clean = -1
    for position in samples:
        if replay.fires(commits[position], predicate):
            firing = position
            while firing - clean > 1:
                middle = (clean + firing) // 2
                if replay.fires(commits[middle], predicate):
                    firing = middle
                else:
                    clean = middle
            return firing
        clean = position
    return None


def to_sample(report: DriftReport) -> Sample:
    return Sample(
        commit=report.commit,
        date=report.date,
        cycles=len(report.cycles),
        largest_cycle=max((len(cycle) for cycle in report.cycles), default=0),
        oversized=len(report.oversized),
        source_lines=report.source_lines,
        test_lines=report.test_lines,
    )


def build_history(
    repo: Path,
    rev: str = "HEAD",
    root: str | None = None,
    budget: int = DEFAULT_BUDGET,
    every: int = DEFAULT_EVERY,
) -> DriftHistory:
    """Trace each metric that fires at rev back to the first commit where it fired."""
    if every < 1:
        raise DriftError("--every must be at least 1")
    final = build_report(repo, rev, root, budget)
    commits = first_parent_commits(repo, final.commit)
    replay = Replay(repo, final.root, budget)
    replay.reports[final.commit] = final
    samples = sample_positions(len(commits), every)
    firings: list[FirstFiring] = []
    for metric, predicate in metrics_for(final):
        position = first_firing(replay, commits, samples, predicate)
        if position is not None:
            commit = commits[position]
            firings.append(FirstFiring(metric, commit.sha, commit.date, commit.subject, position))
    reports = [replay.report(commits[position]) for position in samples]
    return DriftHistory(
        rev=rev,
        root=final.root,
        budget=budget,
        every=every,
        commits=len(commits),
        final_cycles=final.cycles,
        firings=tuple(firings),
        series=tuple(to_sample(report) for report in reports if report is not None),
    )
