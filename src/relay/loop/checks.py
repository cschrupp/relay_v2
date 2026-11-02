"""Run a packet's acceptance commands in its worktree."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

TIMEOUT_SECONDS = 30 * 60
TAIL_LINES = 15


@dataclass(frozen=True)
class CheckResult:
    command: str
    exit_code: int
    tail: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


def run_checks(directory: Path, commands: tuple[str, ...]) -> list[CheckResult]:
    """Run every command through the shell, in order, keeping the end of its output."""
    results: list[CheckResult] = []
    for command in commands:
        try:
            done = subprocess.run(
                command,
                shell=True,
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )
            code, output = done.returncode, done.stdout + done.stderr
        except subprocess.TimeoutExpired:
            code, output = -1, f"timed out after {TIMEOUT_SECONDS} s"
        tail = "\n".join(output.strip().splitlines()[-TAIL_LINES:])
        results.append(CheckResult(command, code, tail))
    return results
