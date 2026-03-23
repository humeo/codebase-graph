"""CLI integration tests."""

import json
import shutil
from pathlib import Path

from click.testing import CliRunner

from codebase_graph.cli import cli
from codebase_graph.storage.db import open_db

FIXTURES = Path(__file__).parent / "fixtures" / "python"
GO_FIXTURES = Path(__file__).parent / "fixtures" / "go"


def _setup_project(tmp_path):
    """Copy fixtures to a temp dir and index them."""
    project = tmp_path / "project"
    project.mkdir()
    for fixture in FIXTURES.iterdir():
        if fixture.is_file():
            shutil.copy(fixture, project / fixture.name)
    return project


def _copy_go_fixture(tmp_path, relative_fixture):
    project = tmp_path / "project"
    shutil.copytree(GO_FIXTURES / relative_fixture, project)
    return project


def test_cli_index(tmp_path):
    project = _setup_project(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["index", str(project)])

    assert result.exit_code == 0
    assert "Indexed" in result.output or "indexed" in result.output


def test_cli_context(tmp_path):
    project = _setup_project(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["index", str(project)])

    result = runner.invoke(cli, ["context", "process_payment", "--root", str(project)])

    assert result.exit_code == 0
    assert "process_payment" in result.output


def test_cli_context_json(tmp_path):
    project = _setup_project(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["index", str(project)])

    result = runner.invoke(
        cli,
        ["context", "process_payment", "--root", str(project), "--json"],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["symbol"]["name"] == "process_payment"


def test_cli_symbol(tmp_path):
    project = _setup_project(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["index", str(project)])

    result = runner.invoke(cli, ["symbol", "Order", "--root", str(project)])

    assert result.exit_code == 0
    assert "Order" in result.output


def test_cli_callers(tmp_path):
    project = _setup_project(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["index", str(project)])

    result = runner.invoke(cli, ["callers", "validate_order", "--root", str(project)])

    assert result.exit_code == 0


def test_cli_callees(tmp_path):
    project = _setup_project(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["index", str(project)])

    result = runner.invoke(cli, ["callees", "process_payment", "--root", str(project)])

    assert result.exit_code == 0
    assert "validate_order" in result.output


def test_cli_file(tmp_path):
    project = _setup_project(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["index", str(project)])

    result = runner.invoke(cli, ["file", "models.py", "--root", str(project)])

    assert result.exit_code == 0
    assert "Order" in result.output


def test_cli_update(tmp_path):
    project = _setup_project(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["index", str(project)])

    result = runner.invoke(cli, ["update", "main.py", "--root", str(project)])

    assert result.exit_code == 0
    assert "Updated" in result.output


def test_cli_update_preserves_go_import_resolution(tmp_path):
    project = _copy_go_fixture(tmp_path, "multi_module/app")
    runner = CliRunner()
    runner.invoke(cli, ["index", str(project)])

    result = runner.invoke(
        cli,
        ["update", "internal/util/util.go", "--root", str(project)],
    )

    assert result.exit_code == 0

    conn = open_db(project)
    resolved = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM edges
        JOIN symbols ON symbols.id = edges.target_id
        WHERE edges.relation = 'imports' AND symbols.kind = 'package'
        """
    ).fetchone()["c"]
    assert resolved > 0


def test_cli_update_removes_deleted_go_file_rows(tmp_path):
    project = _copy_go_fixture(tmp_path, "multi_module/app")
    runner = CliRunner()
    runner.invoke(cli, ["index", str(project)])

    deleted = project / "internal" / "util" / "util.go"
    deleted.unlink()

    result = runner.invoke(
        cli,
        ["update", "internal/util/util.go", "--root", str(project)],
    )

    assert result.exit_code == 0

    conn = open_db(project)
    remaining = conn.execute(
        "SELECT COUNT(*) AS c FROM files WHERE path = ?",
        ("internal/util/util.go",),
    ).fetchone()["c"]
    assert remaining == 0


def test_cli_stats(tmp_path):
    project = _setup_project(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["index", str(project)])

    result = runner.invoke(cli, ["stats", "--root", str(project)])

    assert result.exit_code == 0
    assert "files" in result.output.lower() or "symbols" in result.output.lower()


def test_cli_context_ambiguous_symbol(tmp_path):
    project = _setup_project(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["index", str(project)])

    result = runner.invoke(cli, ["context", "__init__", "--root", str(project)])

    assert result.exit_code == 1
    assert "Ambiguous query: __init__" in result.output


def test_cli_hook_install_reports_incompatible_hook(tmp_path):
    project = tmp_path / "project"
    hooks_dir = project / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    hook_path = hooks_dir / "post-commit"
    hook_path.write_text('#!/usr/bin/env python3\nprint("hi")\n', encoding="utf-8")
    hook_path.chmod(0o755)

    runner = CliRunner()
    result = runner.invoke(cli, ["hook", "install", "--root", str(project)])

    assert result.exit_code == 0
    assert "non-shell hook" in result.output.lower()
