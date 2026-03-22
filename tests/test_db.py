"""Tests for DB CRUD operations."""

from codebase_graph.storage.db import (
    get_file_by_path,
    get_symbols_by_file,
    insert_edge,
    insert_symbol,
    resolve_edges,
    upsert_file,
)


def test_upsert_file_insert(db):
    file_id = upsert_file(db, "src/main.py", "python", "abc123")
    assert file_id is not None
    row = get_file_by_path(db, "src/main.py")
    assert row["language"] == "python"
    assert row["content_hash"] == "abc123"


def test_upsert_file_update(db):
    file_id1 = upsert_file(db, "src/main.py", "python", "abc123")
    file_id2 = upsert_file(db, "src/main.py", "python", "def456")
    assert file_id1 == file_id2
    row = get_file_by_path(db, "src/main.py")
    assert row["content_hash"] == "def456"


def test_insert_symbol(db):
    file_id = upsert_file(db, "src/main.py", "python", "abc123")
    sym_id = insert_symbol(
        db,
        name="process",
        qualified_name="main.process",
        kind="function",
        file_id=file_id,
        line_start=10,
        line_end=25,
        signature="def process(data: list) -> dict",
    )
    assert sym_id is not None
    symbols = get_symbols_by_file(db, file_id)
    assert len(symbols) == 1
    assert symbols[0]["name"] == "process"


def test_insert_edge(db):
    file_id = upsert_file(db, "src/main.py", "python", "abc123")
    src_id = insert_symbol(
        db, "caller", "main.caller", "function", file_id, 1, 5, "def caller()"
    )
    insert_edge(
        db,
        source_id=src_id,
        target_name="callee",
        relation="calls",
        file_id=file_id,
        line=3,
    )
    row = db.execute("SELECT * FROM edges WHERE source_id = ?", (src_id,)).fetchone()
    assert row["target_name"] == "callee"
    assert row["target_id"] is None


def test_resolve_edges(db):
    file_id = upsert_file(db, "src/main.py", "python", "abc123")
    src_id = insert_symbol(
        db, "caller", "main.caller", "function", file_id, 1, 5, "def caller()"
    )
    tgt_id = insert_symbol(
        db, "callee", "main.callee", "function", file_id, 10, 20, "def callee()"
    )
    insert_edge(
        db,
        source_id=src_id,
        target_name="callee",
        relation="calls",
        file_id=file_id,
        line=3,
    )
    resolved = resolve_edges(db)
    assert resolved > 0
    row = db.execute(
        "SELECT target_id FROM edges WHERE source_id = ?", (src_id,)
    ).fetchone()
    assert row["target_id"] == tgt_id
