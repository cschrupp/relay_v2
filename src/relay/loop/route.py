"""Routing: the model a packet starts on, and where its cascade escalates to.

The packet's role picks the entry in `.relay/models.yaml` (read from the repository's
working tree, like any local setting), its tier picks the model. A cheap packet
escalates to the role's strong model when there is one.
"""

from pathlib import Path

from relay.domain import MODELS_PATH, ModelChoice, ModelsError, Role, Tier, parse_models
from relay.loop.cascade import AgentSettings, Cascade


def settings_for(agent: str, choice: ModelChoice) -> AgentSettings:
    return AgentSettings(agent, choice.provider, choice.model, choice.price)


def route(repo: Path, role: Role, tier: Tier, agent: str | None) -> tuple[AgentSettings, Cascade]:
    """The starting model and the cascade for a packet, from `.relay/models.yaml`."""
    path = repo / MODELS_PATH
    if not path.is_file():
        raise ModelsError(f"{MODELS_PATH} not found in {repo}; add it or pass --model")
    models = parse_models(path.read_text(encoding="utf-8")).role(role)
    if models is None:
        raise ModelsError(f"{MODELS_PATH} has no models for the {role} role")
    choice = models.tier(tier)
    if choice is None:
        raise ModelsError(f"{MODELS_PATH} has no {tier} model for the {role} role")
    name = agent or models.agent or role
    strong = models.strong if tier == "cheap" else None
    return settings_for(name, choice), Cascade(settings_for(name, strong) if strong else None)
