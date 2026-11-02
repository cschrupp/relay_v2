"""Server-sent events: split a stream of lines into frames."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class SseFrame:
    id: str | None
    event: str | None
    data: str


def parse_sse(lines: Iterable[str]) -> Iterator[SseFrame]:
    """Yield one frame per blank-line-terminated block that carries data."""
    frame_id: str | None = None
    event: str | None = None
    data: list[str] = []
    for line in lines:
        if not line:
            if data:
                yield SseFrame(frame_id, event, "\n".join(data))
            frame_id, event, data = None, None, []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if field == "data":
            data.append(value)
        elif field == "event":
            event = value
        elif field == "id":
            frame_id = value
    if data:
        yield SseFrame(frame_id, event, "\n".join(data))
