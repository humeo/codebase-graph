#!/usr/bin/env python3
"""Fail CI if the pushed release tag and package version disagree."""

from pathlib import Path
import sys

from codebase_graph.release import verify_release_tag


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: verify_release_version.py <tag>", file=sys.stderr)
        return 2

    tag = argv[1]
    repo_root = Path(__file__).resolve().parent.parent
    pyproject = repo_root / "pyproject.toml"
    package_init = repo_root / "src" / "codebase_graph" / "__init__.py"

    try:
        verify_release_tag(tag, pyproject, package_init)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Release tag {tag} matches pyproject.toml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
