from decimal import Decimal

import pytest

from relay.domain import ModelsError, TokenPrice, parse_models

MODELS = """
implementer:
  agent: implementer
  cheap:
    provider: openrouter
    model: deepseek/deepseek-v4.1-flash
    family: deepseek
    price: {input_per_mtok: "0.10", output_per_mtok: "0.40"}
  strong: {provider: anthropic, model: claude-sonnet-5-5, family: claude}
reviewer:
  strong: {provider: openai, model: gpt-5.5, family: gpt}
"""


def test_models_file_maps_roles_to_tiers() -> None:
    config = parse_models(MODELS)

    implementer = config.role("implementer")
    assert implementer is not None and implementer.agent == "implementer"
    cheap, strong = implementer.tier("cheap"), implementer.tier("strong")
    assert cheap is not None and cheap.model == "deepseek/deepseek-v4.1-flash"
    assert cheap.price == TokenPrice(
        input_per_mtok=Decimal("0.10"), output_per_mtok=Decimal("0.40")
    )
    assert strong is not None and strong.price is None
    assert config.role("architect") is None
    reviewer = config.role("reviewer")
    assert reviewer is not None and reviewer.tier("cheap") is None


def test_reviewer_in_the_implementers_family_is_rejected() -> None:
    same = MODELS.replace("family: gpt", "family: Claude")

    with pytest.raises(ModelsError, match=r"reviewer shares a model family .*\(claude\)"):
        parse_models(same)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("implementer: {agent: x}\n", "cheap or a strong model"),
        ("implementer:\n  cheap: {provider: p, model: m}\n", "family"),
        ("- implementer\n", "mapping of roles"),
        ("tester:\n  cheap: {provider: p, model: m, family: f}\n", "tester"),
        ("implementer: [\n", "cannot read"),
    ],
)
def test_invalid_models_files_are_refused(text: str, message: str) -> None:
    with pytest.raises(ModelsError, match=message):
        parse_models(text)


def test_price_table_cost() -> None:
    price = TokenPrice(input_per_mtok=Decimal("0.10"), output_per_mtok=Decimal("0.40"))

    assert price.cost(23056, 1826) == Decimal("0.0030360")
