"""Report the share of commits that touch no product code (src/ or tests/).

Informational only: DEVELOPMENT.md asks for a review when the share stays above
the threshold. Needs full history (actions/checkout with fetch-depth: 0).
"""

import subprocess
import sys

THRESHOLD = 0.15
PRODUCT_PREFIXES = ("src/", "tests/")
COMMIT_MARKER = "commit-boundary"


def changed_files_by_commit() -> list[list[str]]:
    """Return the list of changed paths for every commit on HEAD, newest first."""
    output = subprocess.run(
        ["git", "log", f"--format=tformat:{COMMIT_MARKER}", "--name-only", "--no-merges"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    commits: list[list[str]] = []
    for line in output.splitlines():
        if line == COMMIT_MARKER:
            commits.append([])
        elif line.strip() and commits:
            commits[-1].append(line.strip())
    return commits


def main() -> int:
    commits = changed_files_by_commit()
    if not commits:
        print("No commits to measure")
        return 0
    process_only = sum(
        not any(path.startswith(PRODUCT_PREFIXES) for path in paths) for paths in commits
    )
    share = process_only / len(commits)
    print(f"{process_only} of {len(commits)} commits touch no src/ or tests/ ({share:.0%})")
    if share > THRESHOLD:
        print(f"Above the {THRESHOLD:.0%} guideline in DEVELOPMENT.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
