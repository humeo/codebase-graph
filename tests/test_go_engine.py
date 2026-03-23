"""Tests for Go language registration and indexing."""

import sqlite3

from codebase_graph.indexer.engine import index_file
from codebase_graph.indexer.languages import supported_suffixes
from codebase_graph.storage.schema import create_tables


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
