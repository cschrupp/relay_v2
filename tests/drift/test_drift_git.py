import os

from conftest import FixtureRepo

from relay.drift.git import first_parent_commits, list_files
from relay.drift.report import build_report


def test_symlinks_are_listed_apart_and_skipped_by_reports(repo: FixtureRepo) -> None:
    repo.commit({"src/pkg/__init__.py": "", "src/pkg/real.py": "x = 1\n", "notes.txt": "n\n"})
    os.symlink("real.py", repo.path / "src/pkg/link.py")
    os.symlink("../notes.txt", repo.path / "src/pkg/notes_link.txt")
    sha = repo.commit({})

    listing = list_files(repo.path, sha)
    report = build_report(repo.path)

    assert sorted(listing.symlinks) == ["src/pkg/link.py", "src/pkg/notes_link.txt"]
    assert "src/pkg/link.py" not in listing.files
    assert report.skipped_symlinks == ("src/pkg/link.py",)
    assert report.unparsable == ()
    assert report.source_files == 2


def test_first_parent_commits_are_oldest_first_with_dates_and_subjects(repo: FixtureRepo) -> None:
    first = repo.commit({"a.txt": "1\n"}, message="first | with pipe")
    second = repo.commit({"a.txt": "2\n"}, message="second")

    commits = first_parent_commits(repo.path, "HEAD")

    assert [(c.sha, c.subject) for c in commits] == [
        (first, "first | with pipe"),
        (second, "second"),
    ]
    assert commits[0].date[:4].isdigit()
