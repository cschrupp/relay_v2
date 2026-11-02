import pytest

from relay.drift.scope import path_allowed


@pytest.mark.parametrize(
    ("pattern", "path", "allowed"),
    [
        # ** : any depth
        ("src/relay/drift/**", "src/relay/drift/card.py", True),
        ("src/relay/drift/**", "src/relay/drift/sub/deep.py", True),
        ("src/relay/drift/**", "src/relay/drifts/x.py", False),
        ("src/**/test_*.py", "src/test_a.py", True),
        ("src/**/test_*.py", "src/a/b/test_a.py", True),
        ("**/fixtures", "tests/drift/fixtures/repo.yaml", True),
        # * : one segment only
        ("src/relay/*.py", "src/relay/main.py", True),
        ("src/relay/*.py", "src/relay/drift/card.py", False),
        ("tests/test_?.py", "tests/test_a.py", True),
        ("tests/test_[ab].py", "tests/test_c.py", False),
        ("tests/test_[!ab].py", "tests/test_c.py", True),
        # directory prefixes
        ("src/relay/drift", "src/relay/drift/card.py", True),
        ("src/relay/drift/", "src/relay/drift/card.py", True),
        ("src/relay/drift/", "src/relay/drift", False),
        ("src/relay/drift", "src/relay/drifter.py", False),
        # unanchored patterns match at any depth; anchored ones only at the root
        ("*.md", "docs/decisions/0002.md", True),
        ("tests", "tests/drift/test_x.py", True),
        ("drift/card.py", "src/relay/drift/card.py", False),
        ("pyproject.toml", "pyproject.toml", True),
    ],
)
def test_gitignore_style_patterns(pattern: str, path: str, allowed: bool) -> None:
    assert path_allowed(path, [pattern]) is allowed


def test_any_pattern_allows() -> None:
    assert path_allowed("README.md", ["src/**", "README.md"])
    assert not path_allowed("README.md", ["src/**", "tests/**"])


def test_negation_is_rejected() -> None:
    with pytest.raises(ValueError, match="not supported"):
        path_allowed("a.py", ["!a.py"])
