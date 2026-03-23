"""Helpers for validating GitHub release metadata."""

from pathlib import Path
import re
import tomllib

PACKAGE_VERSION_RE = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')


def normalize_release_tag(tag: str) -> str:
    return tag if tag.startswith("v") else f"v{tag}"


def project_version_from_pyproject(pyproject_path: Path) -> str:
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    return data["project"]["version"]


def package_version_from_init(package_init_path: Path) -> str:
    match = PACKAGE_VERSION_RE.search(package_init_path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(
            f"Unable to determine package version from {package_init_path}."
        )
    return match.group(1)


def verify_release_tag(
    tag: str,
    pyproject_path: Path,
    package_init_path: Path | None = None,
) -> None:
    normalized = normalize_release_tag(tag)
    expected = normalize_release_tag(project_version_from_pyproject(pyproject_path))
    if normalized != expected:
        raise ValueError(
            f"Release tag {normalized!r} does not match pyproject version {expected!r}."
        )

    if package_init_path is None:
        return

    package_version = normalize_release_tag(package_version_from_init(package_init_path))
    if package_version != expected:
        raise ValueError(
            f"package version {package_version!r} does not match pyproject version {expected!r}."
        )
