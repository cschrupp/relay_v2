import json

import pytest
from conftest import FixtureRepo, long_function

from relay.cli.main import main

PROJECT: dict[str, str | None] = {
    "src/pkg/__init__.py": "",
    "src/pkg/a/__init__.py": "from pkg.b import x\n",
    "src/pkg/b/__init__.py": "from pkg.a import y\n",
    **{f"src/pkg/m{i}.py": long_function(f"f{i}", 81 + i) for i in range(12)},
}


def test_json_output(repo: FixtureRepo, capsys: pytest.CaptureFixture[str]) -> None:
    sha = repo.commit(PROJECT)

    code = main(["drift", "report", str(repo.path), "--json"])

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["commit"] == sha
    assert report["cycles"] == [["a", "b"]]
    assert len(report["oversized"]) == 12
    assert report["oversized"][0] == {
        "path": "src/pkg/m11.py",
        "line": 1,
        "name": "f11",
        "lines": 92,
    }


def test_table_output(repo: FixtureRepo, capsys: pytest.CaptureFixture[str]) -> None:
    repo.commit(PROJECT)

    code = main(["drift", "report", str(repo.path), "--budget", "80"])

    out = capsys.readouterr().out
    assert code == 0
    assert "Import cycles between top-level packages: 1" in out
    assert "2 packages: a, b" in out
    assert "Functions over 80 lines: 12" in out
    assert "... and 2 more (--json lists all)" in out


def test_errors_exit_2(repo: FixtureRepo, capsys: pytest.CaptureFixture[str]) -> None:
    repo.commit(PROJECT)

    code = main(["drift", "report", str(repo.path), "--rev", "nope"])

    assert code == 2
    assert capsys.readouterr().err.startswith("relay: git rev-parse failed")


def test_budget_must_be_positive() -> None:
    with pytest.raises(SystemExit):
        main(["drift", "report", ".", "--budget", "0"])
