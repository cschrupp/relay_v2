"""Matching changed paths against a work packet's allowed paths.

Patterns follow gitignore syntax, the least surprising choice for paths in a repository:

- A pattern with a slash at the start or in the middle (`src/relay/drift`) is anchored at
  the repository root. Without one (`*.md`, `tests`) it matches at any depth.
- `*` matches anything but `/`, `?` one character but `/`, `[abc]` and `[!abc]` a class.
- `**/` at the start or `/**/` in the middle matches zero or more directories; `/**` at the
  end matches everything inside.
- A pattern that matches a directory matches every file under it, so `src/relay/drift`
  and `src/relay/drift/` allow the whole package. A trailing `/` matches directories only.
- Negation (`!pattern`) is not supported and raises ValueError.
"""

import re
from collections.abc import Iterable
from functools import cache


def translate_segment(segment: str) -> str:
    """Regex for one path segment without `/`."""
    out: list[str] = []
    index = 0
    while index < len(segment):
        char = segment[index]
        close = segment.find("]", index + 2)
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[" and close != -1:
            body = segment[index + 1 : close]
            negated = body.startswith("!")
            out.append(f"[{'^' if negated else ''}{re.escape(body.removeprefix('!'))}]")
            index = close
        else:
            out.append(re.escape(char))
        index += 1
    return "".join(out)


@cache
def pattern_regex(pattern: str) -> re.Pattern[str]:
    """Compile one gitignore-style pattern into a regex over repository-relative paths."""
    if pattern.startswith("!"):
        raise ValueError(f"negated pattern {pattern!r} is not supported")
    directory_only = pattern.endswith("/")
    anchored = "/" in pattern.rstrip("/")
    segments = pattern.strip("/").split("/")
    pieces: list[str] = []
    for position, segment in enumerate(segments):
        last = position == len(segments) - 1
        if segment == "**":
            pieces.append(".*" if last else "(?:.*/)?")
        else:
            pieces.append(translate_segment(segment) + ("" if last else "/"))
    prefix = "" if anchored else "(?:.*/)?"
    suffix = "/.*" if directory_only else "(?:/.*)?"
    return re.compile(f"{prefix}{''.join(pieces)}{suffix}")


def path_allowed(path: str, patterns: Iterable[str]) -> bool:
    """Whether a repository-relative file path matches any allowed pattern."""
    return any(pattern_regex(pattern).fullmatch(path) for pattern in patterns)
