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


def test_index_directory_indexes_standalone_go_file_without_project_context(tmp_path):
    source_file = tmp_path / "main.go"
    source_file.write_text("package main\n\nfunc main() {}\n", encoding="utf-8")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    stats = index_directory(conn, tmp_path)

    assert stats["files_scanned"] == 1
    symbols = conn.execute(
        "SELECT kind, qualified_name FROM symbols ORDER BY id"
    ).fetchall()
    assert [(row["kind"], row["qualified_name"]) for row in symbols] == [
        ("module", "main.go"),
        ("function", "main"),
    ]


def test_index_directory_ignores_skipped_go_paths_when_building_context(tmp_path):
    skipped_file = tmp_path / "node_modules" / "x" / "main.go"
    skipped_file.parent.mkdir(parents=True)
    skipped_file.write_text("package main\n\nfunc main() {}\n", encoding="utf-8")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    stats = index_directory(conn, tmp_path)

    assert stats["files_scanned"] == 0
    file_count = conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"]
    assert file_count == 0


def test_index_directory_mixed_tree_allows_go_files_without_matching_context(tmp_path):
    (tmp_path / "main.go").write_text("package main\n\nfunc main() {}\n", encoding="utf-8")
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "go.mod").write_text("module example.com/app\n", encoding="utf-8")
    (app_dir / "util.go").write_text("package app\n\nfunc Run() {}\n", encoding="utf-8")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    stats = index_directory(conn, tmp_path)

    assert stats["files_scanned"] == 2
    file_paths = {
        row["path"] for row in conn.execute("SELECT path FROM files ORDER BY path").fetchall()
    }
    assert file_paths == {"app/util.go", "main.go"}


def test_index_directory_ignores_skipped_go_files_inside_module_context(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "go.mod").write_text("module example.com/app\n", encoding="utf-8")
    (app_dir / "util.go").write_text("package app\n\nfunc Run() {}\n", encoding="utf-8")

    ignored_file = app_dir / "node_modules" / "x" / "bad.go"
    ignored_file.parent.mkdir(parents=True)
    ignored_file.write_text("this is not valid go\n", encoding="utf-8")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    stats = index_directory(conn, tmp_path)

    assert stats["files_scanned"] == 1
    file_paths = {
        row["path"] for row in conn.execute("SELECT path FROM files ORDER BY path").fetchall()
    }
    assert file_paths == {"app/util.go"}


def test_index_directory_reindexes_go_files_when_module_context_changes(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "go.mod").write_text("module example.com/app\n", encoding="utf-8")
    (app_dir / "util.go").write_text("package app\n\nfunc Run() {}\n", encoding="utf-8")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    index_directory(conn, tmp_path)
    (app_dir / "go.mod").write_text("module example.com/renamed-app\n", encoding="utf-8")

    index_directory(conn, tmp_path)

    rows = conn.execute(
        "SELECT kind, qualified_name FROM symbols WHERE kind = 'package' ORDER BY qualified_name"
    ).fetchall()
    assert [row["qualified_name"] for row in rows] == ["example.com/renamed-app"]


def test_index_directory_skips_malformed_go_files_during_context_building(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "go.mod").write_text("module example.com/app\n", encoding="utf-8")
    (app_dir / "util.go").write_text("package app\n\nfunc Run() {}\n", encoding="utf-8")
    (app_dir / "bad.go").write_text("this is not valid go\n", encoding="utf-8")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)

    stats = index_directory(conn, tmp_path)

    assert stats["files_scanned"] == 2
    package_rows = conn.execute(
        "SELECT qualified_name FROM symbols WHERE kind = 'package' ORDER BY qualified_name"
    ).fetchall()
    assert [row["qualified_name"] for row in package_rows] == ["example.com/app"]
