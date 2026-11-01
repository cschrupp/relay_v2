import pytest
from conftest import FixtureRepo, long_function

from relay.drift.history import build_history, sample_positions
from relay.drift.report import DriftError

PACKAGES: dict[str, str | None] = {
    "src/pkg/__init__.py": "",
    "src/pkg/a/__init__.py": "",
    "src/pkg/b/__init__.py": "",
}


def build_drifting_history(repo: FixtureRepo) -> list[str]:
    """Commits 0..6: no package, clean, clean, oversized, clean, a<->b cycle, b<->c added."""
    return [
        repo.commit({"README.md": "start\n"}),
        repo.commit(PACKAGES),
        repo.commit({"src/pkg/a/util.py": "x = 1\n"}),
        repo.commit({"src/pkg/a/big.py": long_function("big", 81)}),
        repo.commit({"src/pkg/a/util.py": "x = 2\n"}),
        repo.commit(
            {"src/pkg/a/util.py": "from pkg.b import y\n", "src/pkg/b/y.py": "import pkg.a\n"}
        ),
        repo.commit(
            {"src/pkg/c/__init__.py": "import pkg.b\n", "src/pkg/b/z.py": "import pkg.c\n"}
        ),
    ]


def firings_by_metric(repo: FixtureRepo, every: int) -> dict[str, int]:
    history = build_history(repo.path, every=every)
    return {firing.metric: firing.position for firing in history.firings}


@pytest.mark.parametrize("every", [1, 2, 3, 10])
def test_first_firing_is_exact_with_any_sampling(repo: FixtureRepo, every: int) -> None:
    build_drifting_history(repo)

    assert firings_by_metric(repo, every) == {
        "any function over 80 lines": 3,
        "any import cycle": 5,
        "cycle inside final cycle 1 (3 packages)": 5,
        "a in a cycle": 5,
        "b in a cycle": 5,
        "c in a cycle": 6,
    }


def test_history_reports_series_and_final_cycles(repo: FixtureRepo) -> None:
    shas = build_drifting_history(repo)

    history = build_history(repo.path, every=3)

    assert history.root == "src/pkg"
    assert history.commits == 7
    assert history.final_cycles == (("a", "b", "c"),)
    assert [sample.commit for sample in history.series] == [shas[3], shas[6]]
    assert [(s.cycles, s.largest_cycle, s.oversized) for s in history.series] == [
        (0, 0, 1),
        (1, 3, 1),
    ]


def test_side_branch_drift_fires_at_its_first_parent_merge(repo: FixtureRepo) -> None:
    repo.commit(PACKAGES)
    repo.git("checkout", "-q", "-b", "side")
    repo.commit({"src/pkg/a/x.py": "import pkg.b\n", "src/pkg/b/x.py": "import pkg.a\n"})
    repo.commit({"src/pkg/a/more.py": "x = 1\n"})
    repo.git("checkout", "-q", "main")
    repo.commit({"src/pkg/b/other.py": "x = 1\n"})
    repo.git("merge", "-q", "--no-ff", "-m", "merge side", "side")

    history = build_history(repo.path, every=1)

    cycle = next(f for f in history.firings if f.metric == "any import cycle")
    assert history.commits == 3
    assert (cycle.position, cycle.subject) == (2, "merge side")


def test_clean_history_fires_nothing(repo: FixtureRepo) -> None:
    repo.commit(PACKAGES)
    repo.commit({"src/pkg/a/x.py": "x = 1\n"})

    assert build_history(repo.path).firings == ()


def test_every_must_be_positive(repo: FixtureRepo) -> None:
    repo.commit(PACKAGES)

    with pytest.raises(DriftError):
        build_history(repo.path, every=0)


def test_sample_positions_always_include_first_and_last() -> None:
    assert sample_positions(7, 3) == [0, 3, 6]
    assert sample_positions(8, 3) == [0, 3, 6, 7]
    assert sample_positions(1, 10) == [0]
