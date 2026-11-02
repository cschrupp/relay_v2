"""The work packet: one bounded task for one agent run."""

from pathlib import Path, PurePosixPath
from typing import Annotated

import yaml
from pydantic import AfterValidator, BeforeValidator, Field, ValidationError

from relay.domain.base import Frozen, LineEstimate, Role, Sha, Text, Tier


class PacketError(ValueError):
    """A work packet file cannot be read or is invalid."""


def reject_unquoted_number(value: object) -> object:
    """YAML reads an all-digit SHA as a number; ask for quotes instead of guessing."""
    if isinstance(value, int | float):
        raise ValueError("write the SHA as a quoted string")
    return value


def relative_path_pattern(value: str) -> str:
    """Allowed paths are repository-relative patterns that stay inside the repository."""
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{value!r} must be relative and must not contain '..'")
    return value


PathPattern = Annotated[Text, AfterValidator(relative_path_pattern)]


class WorkPacket(Frozen):
    goal: Text
    base_sha: Annotated[Sha, BeforeValidator(reject_unquoted_number)]
    allowed_paths: Annotated[tuple[PathPattern, ...], Field(min_length=1)]
    expected_lines: LineEstimate
    acceptance_commands: Annotated[tuple[Text, ...], Field(min_length=1)]
    token_budget: Annotated[int, Field(gt=0)]
    role: Role
    tier: Tier
    issue: Annotated[int, Field(gt=0)] | None = None


def load_work_packet(path: Path) -> WorkPacket:
    """Read and validate a work packet from a YAML file."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise PacketError(f"{path}: cannot read packet: {error}") from error
    if not isinstance(data, dict):
        raise PacketError(f"{path}: a packet must be a YAML mapping")
    try:
        return WorkPacket.model_validate(data)
    except ValidationError as error:
        raise PacketError(f"{path}: invalid packet:\n{error}") from error
