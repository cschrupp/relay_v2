"""The project's own rules in `.relay/rules.yaml`: one schema and loader for every layer.

Defined so far:
- `max_branches`: how many branches besides the default one may exist. When absent,
  the budget is the number of open pull requests plus `BRANCH_ALLOWANCE`.

`relay run` (#8) extends this schema with the rules the developer makes while steering.
"""

from typing import Annotated

import yaml
from pydantic import Field, ValidationError

from relay.domain.base import Frozen

RULES_PATH = ".relay/rules.yaml"
BRANCH_ALLOWANCE = 2


class RulesError(ValueError):
    """The rules file is invalid."""


class Rules(Frozen):
    max_branches: Annotated[int, Field(ge=0)] | None = None

    def branch_budget(self, open_pull_requests: int | None) -> int | None:
        """The branch budget, or None when it depends on an unknown open PR count."""
        if self.max_branches is not None:
            return self.max_branches
        if open_pull_requests is None:
            return None
        return open_pull_requests + BRANCH_ALLOWANCE


def parse_rules(text: str | None) -> Rules:
    """Parse the rules file's text; a missing or empty file means the defaults."""
    try:
        data = yaml.safe_load(text) if text else None
    except yaml.YAMLError as error:
        raise RulesError(f"{RULES_PATH}: cannot read rules: {error}") from error
    if data is None:
        return Rules()
    if not isinstance(data, dict):
        raise RulesError(f"{RULES_PATH}: rules must be a YAML mapping")
    try:
        return Rules.model_validate(data)
    except ValidationError as error:
        raise RulesError(f"{RULES_PATH}: invalid rules:\n{error}") from error
