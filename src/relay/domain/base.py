"""Shared building blocks for domain types."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Role = Literal["architect", "implementer", "reviewer"]
Tier = Literal["cheap", "strong"]
Sha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{7,40}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Count = Annotated[int, Field(ge=0)]


class Frozen(BaseModel):
    """Immutable, strict about unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class NetLines(Frozen):
    """Measured net lines of source and of tests; negative when a change removes code."""

    source: int
    tests: int


class LineEstimate(Frozen):
    """Expected net lines, kept apart so test-heavy work does not read as bloat."""

    source: Count
    tests: Count
