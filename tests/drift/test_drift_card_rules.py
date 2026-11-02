from conftest import FixtureRepo
from test_drift_card import BASE, IMPORTLINTER, packet

from relay.drift.card import build_card, is_rule_path


def test_rule_paths() -> None:
    assert is_rule_path(".importlinter")
    assert is_rule_path(".relay/rules.yaml")
    assert not is_rule_path("src/.relay.py")
    assert not is_rule_path("docs/.importlinter.md")


def test_changing_rule_files_is_blocking(repo: FixtureRepo) -> None:
    base = repo.commit({**BASE, ".relay/rules.yaml": "max_branches: 3\n"})
    repo.commit(
        {
            ".importlinter": IMPORTLINTER.replace("pkg.low", "pkg.lower"),
            ".relay/rules.yaml": None,
            ".relay/new.yaml": "x: 1\n",
        }
    )

    card = build_card(repo.path, packet(base), "HEAD")

    rules = [(f.path, f.message, f.severity) for f in card.findings if f.kind == "edited_rule"]
    assert rules == [
        (".importlinter", "rule file edited", "blocking"),
        (".relay/new.yaml", "rule file added", "blocking"),
        (".relay/rules.yaml", "rule file deleted", "blocking"),
    ]
    assert card.blocking
