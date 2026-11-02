from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hygiene_fixture import RemoteRepo

from relay.cli.main import main
from relay.drift.hygiene import PullRequest
from relay.drift.tidy import apply_action, plan_tidy

NOW = datetime.now(UTC)
LATER = NOW + timedelta(days=30)


@pytest.fixture
def remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RemoteRepo:
    return RemoteRepo(tmp_path, monkeypatch)


def plan(
    remote: RemoteRepo, prs: list[PullRequest] | None, now: datetime = NOW
) -> set[tuple[str, str, bool]]:
    return {(a.ref, a.reason, a.archive) for a in plan_tidy(remote.repo.path, prs, now)}


def test_plan_lists_merged_refs_without_archiving(remote: RemoteRepo) -> None:
    remote.branch("done", merged=True)

    assert plan(remote, []) == {
        ("refs/heads/done", "merged into the default branch", False),
        ("refs/remotes/origin/done", "merged into the default branch", False),
    }


def test_plan_lists_squash_merged_and_stale_refs_with_archiving(remote: RemoteRepo) -> None:
    remote.branch("squashed", merged=False, local=False)
    remote.branch("old", merged=False, local=False)
    prs = [PullRequest(4, "squashed", "MERGED")]

    assert plan(remote, prs, LATER) == {
        ("refs/remotes/origin/squashed", "PR #4 merged", True),
        ("refs/remotes/origin/old", "no open PR and no commits in 14 days", True),
    }


def test_never_plans_default_open_pr_worktree_or_current_branches(
    remote: RemoteRepo, tmp_path: Path
) -> None:
    remote.branch("open", merged=False)
    remote.branch("free", merged=True, local=False)
    remote.branch("in-worktree", merged=True)
    remote.repo.git("worktree", "add", "-q", str(tmp_path / "wt"), "in-worktree")
    remote.branch("current", merged=True, push=False)
    remote.repo.git("checkout", "-q", "current")
    prs = [PullRequest(1, "open", "OPEN"), PullRequest(2, "main", "MERGED")]

    assert {ref for ref, _, _ in plan(remote, prs, LATER)} == {"refs/remotes/origin/free"}


def test_unknown_pr_state_lists_only_contained_refs(remote: RemoteRepo) -> None:
    remote.branch("done", merged=True, local=False)
    remote.branch("old", merged=False, local=False)

    assert plan(remote, None, LATER) == {
        ("refs/remotes/origin/done", "merged into the default branch", False)
    }


def test_apply_archives_unmerged_refs_before_deleting(remote: RemoteRepo) -> None:
    sha = remote.branch("old", merged=False)
    remote.branch("done", merged=True)
    actions = plan_tidy(remote.repo.path, [], LATER)

    results = [apply_action(remote.repo.path, action) for action in actions]

    assert remote.remote_branches() == {"main"}
    assert remote.local_branches() == {"main"}
    assert remote.remote_tags() == {"archive/old"}
    assert remote.repo.git("rev-parse", "archive/old^{commit}") == sha
    assert any(r.startswith("tagged archive/old and pushed it") for r in results)


def test_archive_tag_conflict_uses_the_sha(remote: RemoteRepo) -> None:
    remote.repo.git("tag", "archive/old", "main")
    sha = remote.branch("old", merged=False, push=False)
    [action] = plan_tidy(remote.repo.path, [], LATER)

    apply_action(remote.repo.path, action)

    assert remote.remote_tags() == {f"archive/old-{sha[:7]}"}
    assert remote.local_branches() == {"main"}


def test_cli_dry_run_changes_nothing_and_apply_deletes(
    remote: RemoteRepo, capsys: pytest.CaptureFixture[str]
) -> None:
    remote.branch("done", merged=True)

    assert main(["tidy", str(remote.repo.path)]) == 0
    dry_run = capsys.readouterr().out
    assert "Dry run: 2 branch refs can go" in dry_run
    assert "Nothing was changed" in dry_run
    assert remote.local_branches() == {"done", "main"}

    assert main(["tidy", str(remote.repo.path), "--apply"]) == 0
    assert "deleted refs/remotes/origin/done" in capsys.readouterr().out
    assert remote.local_branches() == {"main"}
    assert remote.remote_branches() == {"main"}


def test_drift_report_has_a_hygiene_section(
    remote: RemoteRepo, capsys: pytest.CaptureFixture[str]
) -> None:
    remote.repo.commit({"src/pkg/__init__.py": "", ".relay/rules.yaml": "max_branches: 0\n"})
    remote.branch("extra", merged=False)

    assert main(["drift", "report", str(remote.repo.path)]) == 0
    out = capsys.readouterr().out
    assert "Branch hygiene (default branch main)" in out
    assert "Drift: 1 branches besides main, budget 0" in out
