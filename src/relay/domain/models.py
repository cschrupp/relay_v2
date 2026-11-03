"""Model routing in `.relay/models.yaml`: which OpenCode agent and model serve each role.

    implementer:
      agent: implementer              # OpenCode agent; defaults to the role's name
      cheap:
        provider: openrouter
        model: deepseek/deepseek-v4.1-flash
        family: deepseek              # model family, stated rather than guessed
        price: {input_per_mtok: 0.10, output_per_mtok: 0.40}   # optional, US$
      strong: {provider: anthropic, model: claude-sonnet-5-5, family: claude}
    reviewer:
      strong: {provider: openai, model: gpt-5.5, family: gpt}

Each role needs at least one tier. Reviewers favour output from their own model family
(LESSONS 23), so no reviewer model may share a family with an implementer model. The
price is used only when the runtime reports no cost.
"""

from decimal import Decimal
from typing import Annotated

import yaml
from pydantic import Field, ValidationError, model_validator

from relay.domain.base import Frozen, Role, Text, Tier

MODELS_PATH = ".relay/models.yaml"
MILLION = Decimal(1_000_000)

Price = Annotated[Decimal, Field(ge=0)]


class ModelsError(ValueError):
    """The models file is missing, unreadable or invalid."""


class TokenPrice(Frozen):
    """US$ per million tokens."""

    input_per_mtok: Price
    output_per_mtok: Price

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        spent = input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok
        return spent / MILLION


class ModelChoice(Frozen):
    provider: Text
    model: Text
    family: Text
    price: TokenPrice | None = None


class RoleModels(Frozen):
    agent: Text | None = None
    cheap: ModelChoice | None = None
    strong: ModelChoice | None = None

    @model_validator(mode="after")
    def has_a_tier(self) -> RoleModels:
        if self.cheap is None and self.strong is None:
            raise ValueError("a role needs a cheap or a strong model")
        return self

    def tier(self, tier: Tier) -> ModelChoice | None:
        return self.cheap if tier == "cheap" else self.strong

    def families(self) -> set[str]:
        return {choice.family.lower() for choice in (self.cheap, self.strong) if choice}


class ModelsConfig(Frozen):
    architect: RoleModels | None = None
    implementer: RoleModels | None = None
    reviewer: RoleModels | None = None

    @model_validator(mode="after")
    def reviewer_family_differs(self) -> ModelsConfig:
        if self.reviewer is None or self.implementer is None:
            return self
        shared = self.reviewer.families() & self.implementer.families()
        if shared:
            families = ", ".join(sorted(shared))
            raise ValueError(
                f"the reviewer shares a model family with the implementer ({families}); "
                "reviewers favour their own family's output, so use another family"
            )
        return self

    def role(self, role: Role) -> RoleModels | None:
        roles = {"architect": self.architect, "implementer": self.implementer}
        return roles.get(role, self.reviewer)


def parse_models(text: str) -> ModelsConfig:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ModelsError(f"{MODELS_PATH}: cannot read: {error}") from error
    if not isinstance(data, dict):
        raise ModelsError(f"{MODELS_PATH}: must be a YAML mapping of roles")
    try:
        return ModelsConfig.model_validate(data)
    except ValidationError as error:
        raise ModelsError(f"{MODELS_PATH}: invalid:\n{error}") from error
