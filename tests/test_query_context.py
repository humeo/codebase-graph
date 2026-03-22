"""Tests for the context query -- the core command."""

import sqlite3
from pathlib import Path

from codebase_graph.indexer.engine import index_directory
from codebase_graph.query.context import query_context
from codebase_graph.storage.schema import create_tables

FIXTURES = Path(__file__).parent / "fixtures" / "python"


def _indexed_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    index_directory(conn, FIXTURES)
    return conn


def test_context_returns_symbol_info():
    conn = _indexed_db()
    result = query_context(conn, "process_payment")
    assert result is not None
    assert result["symbol"]["name"] == "process_payment"
    assert result["symbol"]["kind"] == "function"
    assert result["symbol"]["file"] is not None


def test_context_returns_callers():
    conn = _indexed_db()
    result = query_context(conn, "process_payment")
    caller_names = {c["name"] for c in result["callers"]}
    assert "run" in caller_names


def test_context_returns_callees():
    conn = _indexed_db()
    result = query_context(conn, "process_payment")
    callee_names = {c["name"] for c in result["callees"]}
    assert "validate_order" in callee_names
    assert "format_currency" in callee_names


def test_context_returns_key_files():
    conn = _indexed_db()
    result = query_context(conn, "process_payment")
    files = {f["path"] for f in result["key_files"]}
    assert any("main.py" in path for path in files)


def test_context_not_found():
    conn = _indexed_db()
    result = query_context(conn, "nonexistent_function")
    assert result is None
