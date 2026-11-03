"""The cascade: what Relay does on its own when an attempt is not good enough.

An attempt is not good enough when an acceptance check fails or the card has a blocking
finding; warnings never are, they always go to the developer. Then, without asking:
1. retry once on the same model, with the card as feedback;
2. if that fails too, escalate once from the cheap tier to the strong one, in a new
   session on the same branch.
After that, or when the packet's token budget is spent, the card goes to the developer.
Each step is recorded as a decision made by Relay. Without a cascade (`--no-cascade`),
every card goes to the developer.
"""

from dataclasses import dataclass
from typing import Literal

from relay.domain import Tier, TokenPrice, WorkPacket
from relay.loop.present import initial_prompt

Step = Literal["retry", "escalate"]


@dataclass(frozen=True)
class AgentSettings:
    agent: str
    provider: str
    model: str
    price: TokenPrice | None = None

    @property
    def name(self) -> str:
        return f"{self.provider}/{self.model}"


@dataclass(frozen=True)
class Cascade:
    """`strong` is where a cheap attempt escalates to; None means no escalation."""

    strong: AgentSettings | None = None


@dataclass
class CascadeState:
    tier: Tier
    retried: bool = False
    escalated: bool = False


def next_step(cascade: Cascade, state: CascadeState) -> Step | None:
    """The automatic step for a failing attempt within budget, if one is left."""
    if not state.retried:
        return "retry"
    if not state.escalated and state.tier == "cheap" and cascade.strong is not None:
        return "escalate"
    return None


def retry_prompt(why: str, card_text: str) -> str:
    return (
        f"Your last attempt is not done: {why}.\n\n"
        f"Drift card of your last attempt:\n{card_text}\n\n"
        "Fix it. Continue the same task on the same branch."
    )


def escalation_prompt(packet: WorkPacket, why: str, card_text: str) -> str:
    return (
        f"{initial_prompt(packet)}\n"
        f"A cheaper model already worked on this branch and stopped short: {why}.\n"
        f"Drift card of its last attempt:\n{card_text}\n\n"
        "Start from the branch as it is; keep what is right and fix the rest."
    )
