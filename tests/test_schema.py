"""Tests for SQLite schema creation."""

import sqlite3

from codebase_graph.storage.schema import TABLES, create_tables


def test_create_tables_creates_all_tables(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    create_tables(conn)

    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row[0] for row in cursor.fetchall()}
    assert tables == {"files", "symbols", "edges"}
    assert tables == TABLES
    conn.close()


def test_create_tables_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    create_tables(conn)
    create_tables(conn)
    conn.close()
