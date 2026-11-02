from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hygiene_fixture import RemoteRepo

from relay.domain import Rules
from relay.drift.hygiene import PullRequest, build_hygiene, pull_requests

NOW = datetime.now(UTC)
LATER = NOW + timedelta(days=30)


@pytest.fixture
def remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RemoteRepo:
    return RemoteRepo(tmp_path, monkeypatch)


def test_counts_merged_open_pr_stale_and_budget(remote: RemoteRepo) -> None:
    remote.branch("done", merged=True)
    remote.branch("squashed", merged=False)
    remote.branch("open", merged=False)
    remote.branch("local-only", merged=False, push=False)
    remote.set_prs((1, "squashed", "MERGED"), (2, "open", "OPEN"))

    hygiene = build_hygiene(remote.repo.path, Rules(), pull_requests(remote.repo.path), NOW)

    assert hygiene.default_branch == "main"
    assert (hygiene.local_branches, hygiene.remote_branches, hygiene.branches) == (4, 3, 4)
    assert hygiene.merged == ("done", "squashed")
    assert hygiene.without_open_pr == ("done", "local-only", "squashed")
    assert hygiene.stale == ()
    assert (hygiene.open_pull_requests, hygiene.budget) == (1, 3)
    assert [f.message for f in hygiene.findings] == ["4 branches besides main, budget 3"]


def test_stale_branches_and_explicit_budget(remote: RemoteRepo) -> None:
    remote.branch("old", merged=False)

    hygiene = build_hygiene(remote.repo.path, Rules(max_branches=1), [], LATER)

    assert hygiene.stale == ("old",)
    assert hygiene.budget == 1
    assert hygiene.findings == ()


def test_unknown_pull_requests_are_reported_as_unknown(remote: RemoteRepo) -> None:
    remote.branch("work", merged=False)
    remote.set_gh("gh: not logged in", exit_code=1)

    prs = pull_requests(remote.repo.path)
    hygiene = build_hygiene(remote.repo.path, Rules(), prs, NOW)

    assert prs is None
    assert (hygiene.without_open_pr, hygiene.open_pull_requests, hygiene.budget) == (None,) * 3
    assert hygiene.findings == ()


def test_gh_output_is_parsed(remote: RemoteRepo) -> None:
    remote.set_prs((7, "feature", "OPEN"))

    assert pull_requests(remote.repo.path) == [PullRequest(7, "feature", "OPEN")]


@pytest.mark.parametrize("output", ["not json", '[{"number": 1}]'])
def test_unexpected_gh_output_is_unknown(remote: RemoteRepo, output: str) -> None:
    remote.set_gh(output)

    assert pull_requests(remote.repo.path) is None


def test_gh_that_cannot_run_is_unknown(remote: RemoteRepo) -> None:
    (remote.bin / "gh").chmod(0o644)

    assert pull_requests(remote.repo.path) is None


def test_repository_without_remote_does_not_call_gh(remote: RemoteRepo) -> None:
    remote.repo.git("remote", "remove", "origin")
    remote.set_prs((1, "x", "OPEN"))

    assert pull_requests(remote.repo.path) is None


def test_leftover_worktrees_are_listed(remote: RemoteRepo, tmp_path: Path) -> None:
    remote.branch("wt", merged=False)
    remote.repo.git("worktree", "add", "-q", str(tmp_path / "wt"), "wt")
    remote.repo.git("worktree", "add", "-q", "--detach", str(tmp_path / "gone"))
    (tmp_path / "gone" / ".git").unlink()

    hygiene = build_hygiene(remote.repo.path, Rules(), [], NOW)

    assert {(Path(t.path).name, t.branch, t.prunable) for t in hygiene.worktrees} == {
        ("wt", "wt", False),
        ("gone", None, True),
    }
