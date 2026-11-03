import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from relay.domain import parse_models

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools" / "check_function_size.py"


@pytest.mark.parametrize("layer", ["domain", "store", "runtime", "drift", "loop", "cli"])
def test_every_layer_imports(layer: str) -> None:
    module = importlib.import_module(f"relay.{layer}")
    assert module.__doc__


def run_checker(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_size_checker_passes_short_functions(tmp_path: Path) -> None:
    source = tmp_path / "short.py"
    source.write_text("def small():\n    return 1\n")

    result = run_checker(source)

    assert result.returncode == 0, result.stdout


def test_size_checker_fails_long_functions(tmp_path: Path) -> None:
    body = "".join(f"    x{i} = {i}\n" for i in range(100))
    source = tmp_path / "long.py"
    source.write_text(f"def large():\n{body}    return 0\n")

    result = run_checker(source)

    assert result.returncode == 1
    assert "large is 102 lines" in result.stdout


def test_size_checker_fails_long_modules(tmp_path: Path) -> None:
    source = tmp_path / "big.py"
    source.write_text("".join(f"x{i} = {i}\n" for i in range(401)))

    result = run_checker(source)

    assert result.returncode == 1
    assert "module is 401 lines (budget 400)" in result.stdout


def test_this_repository_routes_by_role() -> None:
    config = parse_models((ROOT / ".relay" / "models.yaml").read_text())

    assert config.role("implementer") and config.role("architect") and config.role("reviewer")
