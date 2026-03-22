"""CLI integration tests."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from codebase_graph.cli import cli


def _write_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()

    (project / "helpers.py").write_text(
        """\
def format_currency(amount):
    return f"${amount:.2f}"


def helper():
    return "helpers"
""",
        encoding="utf-8",
    )
    (project / "models.py").write_text(
        """\
class Order:
    def __init__(self, total):
        self.total = total


def validate_order(order):
    return order.total > 0


def helper():
    return "models"
""",
        encoding="utf-8",
    )
    (project / "main.py").write_text(
        """\
from helpers import format_currency
from models import Order, validate_order


def process_payment(order):
    validate_order(order)
    return format_currency(order.total)


class PaymentProcessor:
    def run(self, order):
        return process_payment(order)
""",
        encoding="utf-8",
    )
    return project


def test_cli_index(tmp_path: Path) -> None:
    project = _write_project(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["index", str(project)])

    assert result.exit_code == 0
    assert "Indexed" in result.output
    assert (project / ".codebase-graph" / "index.db").exists()


def test_cli_context(tmp_path: Path) -> None:
    project = _write_project(tmp_path)
    runner = CliRunner()

    runner.invoke(cli, ["index", str(project)])
    result = runner.invoke(cli, ["context", "process_payment", "--root", str(project)])

    assert result.exit_code == 0
    assert "process_payment" in result.output
    assert "Called by" in result.output
    assert "Calls" in result.output


def test_cli_context_json(tmp_path: Path) -> None:
    project = _write_project(tmp_path)
    runner = CliRunner()

    runner.invoke(cli, ["index", str(project)])
    result = runner.invoke(
        cli,
        ["context", "process_payment", "--root", str(project), "--json"],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["symbol"]["name"] == "process_payment"
    assert data["callers"]
    assert data["callees"]


def test_cli_context_handles_ambiguous_names(tmp_path: Path) -> None:
    project = _write_project(tmp_path)
    runner = CliRunner()

    runner.invoke(cli, ["index", str(project)])
    result = runner.invoke(cli, ["context", "helper", "--root", str(project)])

    assert result.exit_code == 0
    assert "Ambiguous" in result.output
    assert "helpers.py" in result.output
    assert "models.py" in result.output


def test_cli_symbol(tmp_path: Path) -> None:
    project = _write_project(tmp_path)
    runner = CliRunner()

    runner.invoke(cli, ["index", str(project)])
    result = runner.invoke(cli, ["symbol", "Order", "--root", str(project)])

    assert result.exit_code == 0
    assert "Order" in result.output
    assert "class" in result.output.lower()


def test_cli_callers(tmp_path: Path) -> None:
    project = _write_project(tmp_path)
    runner = CliRunner()

    runner.invoke(cli, ["index", str(project)])
    result = runner.invoke(
        cli,
        ["callers", "validate_order", "--root", str(project)],
    )

    assert result.exit_code == 0
    assert "process_payment" in result.output


def test_cli_stats(tmp_path: Path) -> None:
    project = _write_project(tmp_path)
    runner = CliRunner()

    runner.invoke(cli, ["index", str(project)])
    result = runner.invoke(cli, ["stats", "--root", str(project)])

    assert result.exit_code == 0
    assert "Files:" in result.output
    assert "Symbols:" in result.output
    assert "Edges:" in result.output
