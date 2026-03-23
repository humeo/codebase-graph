"""Helpers for validating GitHub release metadata."""

from pathlib import Path
import tomllib


def normalize_release_tag(tag: str) -> str:
    return tag if tag.startswith("v") else f"v{tag}"


def project_version_from_pyproject(pyproject_path: Path) -> str:
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    return data["project"]["version"]


def verify_release_tag(tag: str, pyproject_path: Path) -> None:
    normalized = normalize_release_tag(tag)
    expected = f"v{project_version_from_pyproject(pyproject_path)}"
    if normalized != expected:
        raise ValueError(
            f"Release tag {normalized!r} does not match pyproject version {expected!r}."
        )
