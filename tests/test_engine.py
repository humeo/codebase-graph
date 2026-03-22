"""Tests for the indexer engine."""

import sqlite3
from pathlib import Path

from codebase_graph.indexer.engine import index_directory, index_file
from codebase_graph.storage.schema import create_tables

FIXTURES = Path(__file__).parent / "fixtures" / "python"


def test_index_single_file(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    index_file(conn, FIXTURES / "models.py", root=FIXTURES)

    symbols = conn.execute("SELECT name, kind FROM symbols ORDER BY name").fetchall()
    names = {row["name"] for row in symbols}
    assert "Order" in names
    assert "Receipt" in names
    assert "validate" in names


def test_index_directory(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    index_directory(conn, FIXTURES)

    file_count = conn.execute("SELECT COUNT(*) as c FROM files").fetchone()["c"]
    assert file_count == 3

    sym_count = conn.execute("SELECT COUNT(*) as c FROM symbols").fetchone()["c"]
    assert sym_count > 0

    edge_count = conn.execute("SELECT COUNT(*) as c FROM edges").fetchone()["c"]
    assert edge_count > 0


def test_incremental_index(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    index_directory(conn, FIXTURES)
    count1 = conn.execute("SELECT COUNT(*) as c FROM symbols").fetchone()["c"]

    index_directory(conn, FIXTURES)
    count2 = conn.execute("SELECT COUNT(*) as c FROM symbols").fetchone()["c"]
    assert count1 == count2


def test_resolve_cross_file_edges(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    index_directory(conn, FIXTURES)

    resolved = conn.execute(
        "SELECT COUNT(*) as c FROM edges WHERE target_id IS NOT NULL"
    ).fetchone()["c"]
    assert resolved > 0
