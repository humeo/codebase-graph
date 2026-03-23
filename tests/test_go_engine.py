"""Tests for Go language registration and indexing."""

import sqlite3
from pathlib import Path

from codebase_graph.indexer.engine import index_directory, index_file
from codebase_graph.indexer.languages import supported_suffixes
from codebase_graph.storage.schema import create_tables

FIXTURES = Path(__file__).parent / "fixtures" / "go"


def _indexed_go_db(root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    index_directory(conn, root)
    return conn


def test_go_suffix_is_supported():
    assert ".go" in supported_suffixes()


def test_index_single_go_file_records_go_language(tmp_path):
    source_file = tmp_path / "main.go"
    source_file.write_text("package main\n\nfunc main() {}\n", encoding="utf-8")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    indexed = index_file(conn, source_file, root=tmp_path)

    assert indexed is True
    row = conn.execute("SELECT language FROM files").fetchone()
    assert row["language"] == "go"


def test_index_single_go_file_records_module_and_function_symbols(tmp_path):
    source_file = tmp_path / "main.go"
    source_file.write_text("package main\n\nfunc main() {}\n", encoding="utf-8")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    indexed = index_file(conn, source_file, root=tmp_path)

    assert indexed is True

    symbols = conn.execute(
        "SELECT name, kind, qualified_name FROM symbols ORDER BY id"
    ).fetchall()
    assert len(symbols) == 2
    assert symbols[0]["name"] == "main.go"
    assert symbols[0]["kind"] == "module"
    assert symbols[0]["qualified_name"] == "main.go"
    assert symbols[1]["name"] == "main"
    assert symbols[1]["kind"] == "function"
    assert symbols[1]["qualified_name"] == "main"

    edge_count = conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"]
    assert edge_count == 0


def test_index_directory_inserts_unique_go_package_symbols():
    conn = _indexed_go_db(FIXTURES / "multi_module" / "app")

    rows = conn.execute(
        "SELECT kind, qualified_name FROM symbols WHERE kind = 'package' ORDER BY qualified_name"
    ).fetchall()

    assert [row["qualified_name"] for row in rows] == [
        "example.com/app/cmd/api",
        "example.com/app/internal/util",
    ]


def test_index_directory_inserts_package_symbol_for_test_only_go_package():
    conn = _indexed_go_db(FIXTURES / "test_only")

    rows = conn.execute(
        "SELECT qualified_name FROM symbols WHERE kind = 'package' ORDER BY qualified_name"
    ).fetchall()

    assert [row["qualified_name"] for row in rows] == ["example.com/test-only/pkg"]
