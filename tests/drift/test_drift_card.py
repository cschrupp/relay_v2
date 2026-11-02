from typing import Any

import pytest
from conftest import FixtureRepo, long_function

from relay.domain import DriftCard, LineEstimate, NetLines, WorkPacket
from relay.drift.card import build_card

IMPORTLINTER = """[importlinter]
root_package = pkg

[importlinter:contract:layers]
name = Pkg layers
type = layers
layers =
    pkg.high
    pkg.low
"""
BASE: dict[str, str | None] = {
    "src/pkg/__init__.py": "",
    "src/pkg/high/__init__.py": "from pkg.low import x\n",
    "src/pkg/low/__init__.py": "x = 1\n",
    "src/pkg/low/grow.py": long_function("grow", 85),
    "tests/test_low.py": "def test_low():\n    pass\n",
    "pyproject.toml": '[project]\nname = "pkg"\ndependencies = ["pydantic>=2"]\n',
    ".importlinter": IMPORTLINTER,
    "README.md": "readme\n",
}


def packet(base_sha: str, **changes: Any) -> WorkPacket:
    fields: dict[str, Any] = {
        "goal": "change low",
        "base_sha": base_sha,
        "allowed_paths": ("src/pkg/**", "tests/**", "pyproject.toml"),
        "expected_lines": LineEstimate(source=20, tests=20),
        "acceptance_commands": ("pytest",),
        "token_budget": 1000,
        "role": "implementer",
        "tier": "cheap",
    }
    return WorkPacket.model_validate({**fields, **changes})


def card_after(repo: FixtureRepo, files: dict[str, str | None], **changes: Any) -> DriftCard:
    base = repo.commit(BASE)
    repo.commit(files)
    return build_card(repo.path, packet(base, **changes), "HEAD")


def kinds(card: DriftCard) -> list[tuple[str, str]]:
    return [(finding.kind, finding.message) for finding in card.findings]


def test_clean_change_has_an_empty_card(repo: FixtureRepo) -> None:
    card = card_after(repo, {"src/pkg/low/more.py": "y = 2\n", "tests/test_more.py": "x = 1\n"})

    assert card.findings == ()
    assert card.actual_lines == NetLines(source=1, tests=1)
    assert len(card.base_sha) == len(card.result_sha) == 40


def test_new_cycle(repo: FixtureRepo) -> None:
    card = card_after(repo, {"src/pkg/low/back.py": "import pkg.high\n"})

    assert ("new_cycle", "import cycle among high, low") in kinds(card)


def test_layer_violation_is_blocking(repo: FixtureRepo) -> None:
    card = card_after(repo, {"src/pkg/low/back.py": "from pkg.high import y\n"})

    [violation] = [f for f in card.findings if f.kind == "layer_violation"]
    assert violation.message == "pkg.low imports pkg.high (Pkg layers)"
    assert (violation.severity, violation.path) == ("blocking", "src/pkg/low/back.py")
    assert card.blocking


def test_existing_violations_are_not_new(repo: FixtureRepo) -> None:
    base = repo.commit({**BASE, "src/pkg/low/old.py": "import pkg.high\n"})
    repo.commit({"src/pkg/low/more.py": "y = 2\n"})

    card = build_card(repo.path, packet(base), "HEAD")

    assert [f.kind for f in card.findings] == []


def test_unsupported_contract_is_reported(repo: FixtureRepo) -> None:
    base = repo.commit(
        {**BASE, ".importlinter": IMPORTLINTER + "\n[importlinter:contract:f]\ntype = forbidden\n"}
    )
    repo.commit({"src/pkg/low/more.py": "y = 2\n"})

    card = build_card(repo.path, packet(base), "HEAD")

    assert kinds(card) == [
        ("unsupported_rule", "contract 'f' not checked: type forbidden is not supported")
    ]


def test_new_and_grown_oversized_functions(repo: FixtureRepo) -> None:
    card = card_after(
        repo,
        {
            "src/pkg/low/grow.py": long_function("grow", 90),
            "src/pkg/low/big.py": long_function("big", 81),
        },
        expected_lines=LineEstimate(source=100, tests=0),
    )

    assert kinds(card) == [
        ("oversized_function", "grow is 90 lines (budget 80, was 85)"),
        ("oversized_function", "big is 81 lines (budget 80)"),
    ]


def test_unchanged_oversized_function_is_not_reported(repo: FixtureRepo) -> None:
    card = card_after(repo, {"src/pkg/low/more.py": "y = 2\n"})

    assert card.findings == ()


@pytest.mark.parametrize(("source", "drifts"), [(30, False), (31, True)])
def test_net_lines_against_the_estimate(repo: FixtureRepo, source: int, drifts: bool) -> None:
    text = "".join(f"x{i} = {i}\n" for i in range(source))

    card = card_after(repo, {"src/pkg/low/more.py": text, "docs/long.md": "x\n" * 500})

    assert card.actual_lines == NetLines(source=source, tests=0)
    expected = [("net_lines", f"source: +{source} net lines against 20 expected")]
    assert [k for k in kinds(card) if k[0] == "net_lines"] == (expected if drifts else [])


def test_files_outside_allowed_paths(repo: FixtureRepo) -> None:
    card = card_after(repo, {"README.md": "changed\n", "src/pkg/low/more.py": "y = 2\n"})

    assert kinds(card) == [("outside_scope", "README.md is outside the allowed paths")]


def test_new_dependency(repo: FixtureRepo) -> None:
    pyproject = '[project]\nname = "pkg"\ndependencies = ["pydantic>=2", "Requests"]\n'

    card = card_after(repo, {"pyproject.toml": pyproject})

    assert kinds(card) == [("new_dependency", "new dependency: requests")]


def test_edited_and_deleted_tests_are_blocking(repo: FixtureRepo) -> None:
    base = repo.commit({**BASE, "tests/test_gone.py": "x = 1\n"})
    repo.commit(
        {"tests/test_low.py": "def test_low():\n    assert True\n", "tests/test_gone.py": None}
    )

    card = build_card(repo.path, packet(base), "HEAD")

    assert [(f.kind, f.message, f.path, f.severity) for f in card.findings] == [
        ("edited_test", "existing test deleted", "tests/test_gone.py", "blocking"),
        ("edited_test", "existing test edited", "tests/test_low.py", "blocking"),
    ]


def test_test_file_with_only_added_lines_is_a_warning(repo: FixtureRepo) -> None:
    extended = "def test_low():\n    pass\n\n\ndef test_more():\n    pass\n"

    card = card_after(repo, {"tests/test_low.py": extended})

    assert [(f.kind, f.message, f.severity) for f in card.findings] == [
        ("edited_test", "existing test file extended", "warning")
    ]
    assert not card.blocking
