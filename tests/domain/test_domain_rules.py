import pytest

from relay.domain import Rules, RulesError, parse_rules


def test_missing_or_empty_rules_mean_defaults() -> None:
    assert parse_rules(None) == Rules()
    assert parse_rules("") == Rules()
    assert parse_rules("# nothing yet\n") == Rules()


def test_branch_budget_defaults_to_open_prs_plus_two() -> None:
    assert Rules().branch_budget(3) == 5
    assert Rules().branch_budget(None) is None
    assert parse_rules("max_branches: 4\n").branch_budget(None) == 4
    assert parse_rules("max_branches: 4\n").branch_budget(10) == 4


@pytest.mark.parametrize(
    "text", ["max_branches: -1\n", "max_branches: many\n", "- a list\n", "surprise: 1\n", "a: [\n"]
)
def test_invalid_rules_are_rejected(text: str) -> None:
    with pytest.raises(RulesError, match=".relay/rules.yaml"):
        parse_rules(text)
