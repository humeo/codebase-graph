"""Tests for release version helpers."""

from pathlib import Path

import pytest

from codebase_graph.release import (
    normalize_release_tag,
    project_version_from_pyproject,
    verify_release_tag,
)


def test_normalize_release_tag_adds_prefix():
    assert normalize_release_tag("0.1.0") == "v0.1.0"


def test_normalize_release_tag_keeps_prefixed_tag():
    assert normalize_release_tag("v0.1.0") == "v0.1.0"


def test_project_version_from_pyproject_reads_project_version(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "codebase-graph"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )

    assert project_version_from_pyproject(pyproject) == "0.1.0"


def test_verify_release_tag_raises_on_version_mismatch(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "codebase-graph"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not match"):
        verify_release_tag("v0.1.1", pyproject)


def test_verify_release_tag_accepts_matching_version(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "codebase-graph"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )

    verify_release_tag("v0.1.0", pyproject)


def test_verify_release_tag_accepts_prefixed_project_version(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "codebase-graph"\nversion = "v0.1.0"\n',
        encoding="utf-8",
    )

    verify_release_tag("0.1.0", pyproject)


def test_verify_release_tag_raises_on_package_version_mismatch(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "codebase-graph"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    package_init = tmp_path / "__init__.py"
    package_init.write_text('__version__ = "0.1.1"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="package version"):
        verify_release_tag("v0.1.0", pyproject, package_init)
