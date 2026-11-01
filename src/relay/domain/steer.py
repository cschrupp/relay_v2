"""The developer's decision after reading a drift card, and the record of a run."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from relay.domain.base import Count, Frozen, Role, Text, Tier


class Accept(Frozen):
    kind: Literal["accept"] = "accept"


class Redirect(Frozen):
    kind: Literal["redirect"] = "redirect"
    text: Text


class MakeRule(Frozen):
    """Turn a correction into a rule. The spec's format belongs to the rules module (#14, #8)."""

    kind: Literal["make_rule"] = "make_rule"
    spec: Text


SteerDecision = Annotated[Accept | Redirect | MakeRule, Field(discriminator="kind")]
STEER_DECISION: TypeAdapter[Accept | Redirect | MakeRule] = TypeAdapter(SteerDecision)

Outcome = Literal["accepted", "redirected", "rejected", "failed", "budget_exceeded"]


class RunRecord(Frozen):
    model: Text
    role: Role
    tier: Tier
    input_tokens: Count
    output_tokens: Count
    cost_usd: Annotated[Decimal, Field(ge=0)] | None = None
    outcome: Outcome
