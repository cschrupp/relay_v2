from pathlib import Path

import pytest
from conftest import FixtureRepo, long_function

from relay.drift.git import GitError
from relay.drift.report import DriftError, build_report

CYCLIC_PROJECT: dict[str, str | None] = {
    "src/pkg/__init__.py": "",
    "src/pkg/a/__init__.py": "from pkg.b import x\n",
    "src/pkg/b/__init__.py": "from pkg.a import y\n",
    "src/pkg/b/big.py": long_function("big", 90),
    "src/pkg/broken.py": "def oops(:\n",
    "tests/test_a.py": "def test_a():\n    pass\n",
    "tools/helper.py": "x = 1\n",
    "README.md": "readme\n",
}


def test_report_measures_cycles_functions_and_sizes(repo: FixtureRepo) -> None:
    sha = repo.commit(CYCLIC_PROJECT)

    report = build_report(repo.path)

    assert report.commit == sha
    assert report.root == "src/pkg"
    assert report.cycles == (("a", "b"),)
    assert [(f.path, f.name, f.lines) for f in report.oversized] == [
        ("src/pkg/b/big.py", "big", 90)
    ]
    assert report.unparsable == ("src/pkg/broken.py",)
    assert (report.source_files, report.source_lines) == (5, 93)
    assert (report.test_files, report.test_lines) == (1, 2)
    assert report.largest_files[0].path == "src/pkg/b/big.py"


def test_report_reads_the_commit_not_the_working_tree(repo: FixtureRepo) -> None:
    first = repo.commit(CYCLIC_PROJECT)
    repo.commit({"src/pkg/b/__init__.py": "", "src/pkg/b/big.py": None})
    (repo.path / "src/pkg/a/__init__.py").write_text(long_function("dirty", 200))

    old = build_report(repo.path, rev=first)
    new = build_report(repo.path)

    assert old.cycles == (("a", "b"),)
    assert len(old.oversized) == 1
    assert new.cycles == ()
    assert new.oversized == ()


def test_explicit_root_and_budget(repo: FixtureRepo) -> None:
    repo.commit({**CYCLIC_PROJECT, "src/other/__init__.py": long_function("f", 30)})

    report = build_report(repo.path, root="src/other/", budget=20)

    assert report.root == "src/other"
    assert [f.name for f in report.oversized] == ["f"]


def test_ambiguous_root_needs_an_explicit_root(repo: FixtureRepo) -> None:
    repo.commit({"src/one/__init__.py": "", "src/two/__init__.py": ""})

    with pytest.raises(DriftError, match="pass --root"):
        build_report(repo.path)


def test_root_without_python_files_is_an_error(repo: FixtureRepo) -> None:
    repo.commit(CYCLIC_PROJECT)

    with pytest.raises(DriftError, match="no Python files under src/missing"):
        build_report(repo.path, root="src/missing")


def test_unknown_revision_is_a_git_error(repo: FixtureRepo) -> None:
    repo.commit(CYCLIC_PROJECT)

    with pytest.raises(GitError):
        build_report(repo.path, rev="no-such-rev")


def test_not_a_repository_is_a_git_error(tmp_path: Path) -> None:
    with pytest.raises(GitError):
        build_report(tmp_path)
