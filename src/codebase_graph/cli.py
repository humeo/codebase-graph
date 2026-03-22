"""CLI entry point for codebase-graph."""

from __future__ import annotations

import ast
import json
import logging
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from . import __version__

@dataclass(slots=True)
class _SymbolRecord:
    name: str
    qualified_name: str
    kind: str
    line_start: int
    line_end: int
    signature: str | None
    exported: bool


def _resolve_root(root: str | None) -> Path:
    return Path(root).expanduser().resolve() if root else Path.cwd().resolve()


def _db_dir(root: Path) -> Path:
    return root / ".codebase-graph"


def _db_path(root: Path) -> Path:
    return _db_dir(root) / "index.db"


def _open_db(root: Path) -> sqlite3.Connection:
    _db_dir(root).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path(root))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _create_tables(conn)
    return conn


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            language TEXT NOT NULL,
            indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            mtime_ns INTEGER NOT NULL DEFAULT 0,
            size INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            qualified_name TEXT NOT NULL,
            kind TEXT NOT NULL,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            line_start INTEGER NOT NULL,
            line_end INTEGER NOT NULL,
            signature TEXT,
            exported INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            source_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
            relation TEXT NOT NULL,
            target_name TEXT NOT NULL,
            target_id INTEGER REFERENCES symbols(id) ON DELETE SET NULL,
            line INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
        CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
        CREATE INDEX IF NOT EXISTS idx_symbols_qualified ON symbols(qualified_name);
        CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);
        CREATE INDEX IF NOT EXISTS idx_symbols_kind ON symbols(kind);
        CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
        CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);
        """
    )
    conn.commit()


def _clear_all(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM edges")
    conn.execute("DELETE FROM symbols")
    conn.execute("DELETE FROM files")
    conn.commit()


def _language_for(path: Path) -> str:
    if path.suffix == ".py":
        return "python"
    return "unknown"


def _is_indexable(path: Path) -> bool:
    return path.is_file() and path.suffix == ".py"


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _source_lines(source: str) -> list[str]:
    return source.splitlines()


def _signature_for_node(lines: list[str], node: ast.AST) -> str | None:
    lineno = getattr(node, "lineno", None)
    if lineno is None or lineno < 1 or lineno > len(lines):
        return None
    return lines[lineno - 1].strip() or None


def _qualified_name(class_stack: list[str], function_stack: list[str], name: str) -> str:
    parts = [*class_stack, *function_stack, name]
    return ".".join(parts)


class _PythonIndexer(ast.NodeVisitor):
    def __init__(self, source: str, rel_path: str) -> None:
        self.source = source
        self.lines = _source_lines(source)
        self.rel_path = rel_path
        self.class_stack: list[str] = []
        self.function_stack: list[str] = []
        self.symbols: list[_SymbolRecord] = []
        self.edges: list[dict[str, Any]] = []
        self._current_symbol: str | None = None

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        qualified = _qualified_name(self.class_stack, self.function_stack, node.name)
        self.symbols.append(
            _SymbolRecord(
                name=node.name,
                qualified_name=qualified,
                kind="class",
                line_start=node.lineno,
                line_end=getattr(node, "end_lineno", node.lineno),
                signature=_signature_for_node(self.lines, node),
                exported=not node.name.startswith("_"),
            )
        )
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._visit_function(node)

    def _visit_function(self, node: ast.AST) -> None:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        kind = "method" if self.class_stack else "function"
        qualified = _qualified_name(self.class_stack, self.function_stack, node.name)
        self.symbols.append(
            _SymbolRecord(
                name=node.name,
                qualified_name=qualified,
                kind=kind,
                line_start=node.lineno,
                line_end=getattr(node, "end_lineno", node.lineno),
                signature=_signature_for_node(self.lines, node),
                exported=not node.name.startswith("_"),
            )
        )
        previous = self._current_symbol
        self.function_stack.append(node.name)
        self._current_symbol = node.name
        self.generic_visit(node)
        self.function_stack.pop()
        self._current_symbol = previous

    def visit_Call(self, node: ast.Call) -> Any:
        if self._current_symbol:
            target_name = None
            if isinstance(node.func, ast.Name):
                target_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                target_name = node.func.attr

            if target_name:
                source_name = _qualified_name(
                    self.class_stack, self.function_stack[:-1], self._current_symbol
                )
                self.edges.append(
                    {
                        "relation": "calls",
                        "source_name": source_name,
                        "target_name": target_name,
                        "line": getattr(node, "lineno", 0),
                    }
                )
        self.generic_visit(node)


def _insert_file(conn: sqlite3.Connection, root: Path, path: Path) -> int:
    rel_path = _relative_path(root, path)
    stat = path.stat()
    language = _language_for(path)
    existing = conn.execute(
        "SELECT id, mtime_ns, size FROM files WHERE path = ?",
        (rel_path,),
    ).fetchone()
    if existing and existing["mtime_ns"] == stat.st_mtime_ns and existing["size"] == stat.st_size:
        return 0

    if existing:
        file_id = existing["id"]
        conn.execute("DELETE FROM edges WHERE file_id = ?", (file_id,))
        conn.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
        conn.execute(
            """
            UPDATE files
               SET language = ?, indexed_at = CURRENT_TIMESTAMP, mtime_ns = ?, size = ?
             WHERE id = ?
            """,
            (language, stat.st_mtime_ns, stat.st_size, file_id),
        )
    else:
        cursor = conn.execute(
            """
            INSERT INTO files (path, language, indexed_at, mtime_ns, size)
            VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)
            """,
            (rel_path, language, stat.st_mtime_ns, stat.st_size),
        )
        file_id = cursor.lastrowid

    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        conn.commit()
        return 0

    visitor = _PythonIndexer(source, rel_path)
    visitor.visit(tree)

    symbol_ids: dict[str, int] = {}
    for symbol in visitor.symbols:
        cursor = conn.execute(
            """
            INSERT INTO symbols (
                name, qualified_name, kind, file_id, line_start, line_end, signature, exported
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol.name,
                symbol.qualified_name,
                symbol.kind,
                file_id,
                symbol.line_start,
                symbol.line_end,
                symbol.signature,
                1 if symbol.exported else 0,
            ),
        )
        symbol_ids[symbol.qualified_name] = cursor.lastrowid
        symbol_ids[symbol.name] = cursor.lastrowid

    for edge in visitor.edges:
        source_id = symbol_ids.get(edge["source_name"])
        if source_id is None:
            continue
        conn.execute(
            """
            INSERT INTO edges (file_id, source_id, relation, target_name, line)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                file_id,
                source_id,
                edge["relation"],
                edge["target_name"],
                edge["line"],
            ),
        )

    conn.commit()
    return 1


def _resolve_edge_targets(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT id, target_name
          FROM edges
         WHERE target_id IS NULL
         ORDER BY id
        """
    ).fetchall()
    resolved = 0
    for row in rows:
        symbol = conn.execute(
            """
            SELECT id
              FROM symbols
             WHERE name = ? OR qualified_name = ?
             ORDER BY CASE kind WHEN 'function' THEN 0 WHEN 'class' THEN 1 WHEN 'method' THEN 2 ELSE 3 END,
                      id
             LIMIT 1
            """,
            (row["target_name"], row["target_name"]),
        ).fetchone()
        if symbol:
            conn.execute(
                "UPDATE edges SET target_id = ? WHERE id = ?",
                (symbol["id"], row["id"]),
            )
            resolved += 1
    conn.commit()
    return resolved


def index_file(conn: sqlite3.Connection, file_path: Path, root: Path) -> bool:
    return bool(_insert_file(conn, root, file_path))


def index_directory(conn: sqlite3.Connection, root: Path) -> dict[str, int]:
    stats = {
        "files_scanned": 0,
        "files_indexed": 0,
        "files_skipped": 0,
        "edges_resolved": 0,
    }

    for current in sorted(root.rglob("*.py")):
        if any(part.startswith(".") for part in current.relative_to(root).parts):
            continue
        if any(part == "__pycache__" for part in current.relative_to(root).parts):
            continue
        stats["files_scanned"] += 1
        changed = _insert_file(conn, root, current)
        if changed:
            stats["files_indexed"] += 1
        else:
            stats["files_skipped"] += 1

    stats["edges_resolved"] = _resolve_edge_targets(conn)
    return stats


def find_symbol(
    conn: sqlite3.Connection, name: str, kind: str | None = None
) -> list[sqlite3.Row]:
    query = (
        """
        SELECT s.*, f.path AS file_path
          FROM symbols s
          JOIN files f ON s.file_id = f.id
         WHERE (s.name = ? OR s.qualified_name = ?)
        """
    )
    params: list[Any] = [name, name]
    if kind:
        query += " AND s.kind = ?"
        params.append(kind)
    query += " ORDER BY CASE s.kind WHEN 'function' THEN 0 WHEN 'class' THEN 1 WHEN 'method' THEN 2 ELSE 3 END, s.name, f.path"
    return conn.execute(query, params).fetchall()


def list_file_symbols(conn: sqlite3.Connection, file_path: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT s.*, f.path AS file_path
          FROM symbols s
          JOIN files f ON s.file_id = f.id
         WHERE f.path = ?
         ORDER BY s.line_start, s.line_end
        """,
        (file_path,),
    ).fetchall()


def _relationship_rows(conn: sqlite3.Connection, symbol_id: int, direction: str) -> list[dict[str, Any]]:
    if direction == "callers":
        rows = conn.execute(
            """
            SELECT DISTINCT s.name, s.qualified_name, s.kind, f.path AS file_path, e.line
              FROM edges e
              JOIN symbols s ON e.source_id = s.id
              JOIN files f ON s.file_id = f.id
             WHERE e.target_id = ? AND e.relation = 'calls'
             ORDER BY f.path, e.line, s.name
            """,
            (symbol_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT DISTINCT COALESCE(ts.name, e.target_name) AS name,
                            ts.qualified_name,
                            ts.kind,
                            tf.path AS file_path,
                            e.line
              FROM edges e
              LEFT JOIN symbols ts ON e.target_id = ts.id
              LEFT JOIN files tf ON ts.file_id = tf.id
             WHERE e.source_id = ? AND e.relation = 'calls'
             ORDER BY e.line, name
            """,
            (symbol_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_callers(conn: sqlite3.Connection, symbol_id: int) -> list[dict[str, Any]]:
    return _relationship_rows(conn, symbol_id, "callers")


def get_callees(conn: sqlite3.Connection, symbol_id: int) -> list[dict[str, Any]]:
    return _relationship_rows(conn, symbol_id, "callees")


def query_context(
    conn: sqlite3.Connection, name: str, depth: int = 1
) -> dict[str, Any] | None:
    matches = find_symbol(conn, name)
    if not matches:
        return None

    if len(matches) > 1 and "." not in name:
        return {
            "ambiguous": True,
            "query": name,
            "matches": [dict(row) for row in matches],
        }

    symbol = matches[0]
    symbol_id = symbol["id"]
    callers = get_callers(conn, symbol_id)
    callees = get_callees(conn, symbol_id)

    file_scores: Counter[str] = Counter()
    file_scores[symbol["file_path"]] += 5
    for caller in callers:
        if caller.get("file_path"):
            file_scores[caller["file_path"]] += 2
    for callee in callees:
        if callee.get("file_path"):
            file_scores[callee["file_path"]] += 1

    key_files = [
        {"path": path, "relevance": score}
        for path, score in file_scores.most_common(max(1, depth * 5))
    ]

    return {
        "symbol": {
            "name": symbol["name"],
            "qualified_name": symbol["qualified_name"],
            "kind": symbol["kind"],
            "file": symbol["file_path"],
            "line_start": symbol["line_start"],
            "line_end": symbol["line_end"],
            "signature": symbol["signature"],
        },
        "callers": callers,
        "callees": callees,
        "imports": [],
        "key_files": key_files,
    }


def format_context_text(result: dict[str, Any]) -> str:
    if result.get("ambiguous"):
        lines = [f"Ambiguous symbol query '{result['query']}'."]
        lines.append("Matches:")
        for match in result["matches"]:
            lines.append(
                f"  {match['kind']:<8s} {match['name']:<20s} {match['file_path']}:{match['line_start']}"
            )
        return "\n".join(lines)

    symbol = result["symbol"]
    lines = [
        f"Symbol: {symbol['name']}",
        f"  Kind: {symbol['kind']}",
        f"  File: {symbol['file']}:{symbol['line_start']}-{symbol['line_end']}",
    ]
    if symbol.get("signature"):
        lines.append(f"  Signature: {symbol['signature']}")

    callers = result.get("callers", [])
    if callers:
        lines.append("")
        lines.append(f"Called by ({len(callers)})")
        for caller in callers:
            lines.append(
                f"  {caller['name']:<20s} {caller.get('file_path', '?')}:{caller.get('line', '?')}"
            )

    callees = result.get("callees", [])
    if callees:
        lines.append("")
        lines.append(f"Calls ({len(callees)})")
        for callee in callees:
            location = (
                f"{callee.get('file_path', '?')}:{callee.get('line', '?')}"
                if callee.get("file_path")
                else "unresolved"
            )
            lines.append(f"  {callee['name']:<20s} {location}")

    key_files = result.get("key_files", [])
    if key_files:
        lines.append("")
        lines.append("Key Files")
        for file_info in key_files:
            lines.append(f"  {file_info['path']}")

    return "\n".join(lines)


def format_json(data: dict[str, Any] | list[Any]) -> str:
    return json.dumps(data, indent=2, default=str)


@click.group()
@click.version_option(version=__version__)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def cli(verbose: bool) -> None:
    """Code navigation & context compression for agents."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)


@cli.command()
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--full", is_flag=True, help="Force full re-index (ignore cache)")
def index(path: Path, full: bool) -> None:
    """Index a codebase for symbol navigation."""
    root = path.resolve()
    conn = _open_db(root)
    if full:
        _clear_all(conn)
    stats = index_directory(conn, root)
    conn.close()

    click.echo(f"Indexed {root}")
    click.echo(f"  Files scanned: {stats['files_scanned']}")
    click.echo(f"  Files indexed: {stats['files_indexed']}")
    click.echo(f"  Files skipped: {stats['files_skipped']} (unchanged)")
    click.echo(f"  Edges resolved: {stats['edges_resolved']}")


@cli.command()
@click.argument("name")
@click.option("--root", default=None, help="Project root")
@click.option("--depth", default=1, type=int, show_default=True, help="Relationship depth")
@click.option("--json", "as_json", is_flag=True, help="JSON output")
def context(name: str, root: str | None, depth: int, as_json: bool) -> None:
    """Show compressed context for a symbol."""
    root_path = _resolve_root(root)
    conn = _open_db(root_path)
    result = query_context(conn, name, depth=depth)
    conn.close()

    if result is None:
        click.echo(f"Symbol '{name}' not found. Run 'cg index' first?", err=True)
        raise SystemExit(1)

    if as_json:
        click.echo(format_json(result))
        return

    click.echo(format_context_text(result))


@cli.command()
@click.argument("name")
@click.option("--root", default=None, help="Project root")
@click.option("--json", "as_json", is_flag=True, help="JSON output")
def callers(name: str, root: str | None, as_json: bool) -> None:
    """Show who calls a symbol."""
    root_path = _resolve_root(root)
    conn = _open_db(root_path)
    syms = find_symbol(conn, name)
    if not syms:
        conn.close()
        click.echo(f"Symbol '{name}' not found.", err=True)
        raise SystemExit(1)

    result = get_callers(conn, syms[0]["id"])
    conn.close()

    if as_json:
        click.echo(format_json(result))
        return

    if not result:
        click.echo(f"No callers found for '{name}'.")
        return

    click.echo(f"Callers of '{name}' ({len(result)}):")
    for item in result:
        click.echo(f"  {item['name']:<20s} {item.get('file_path', '?')}:{item.get('line', '?')}")


@cli.command()
@click.argument("name")
@click.option("--root", default=None, help="Project root")
@click.option("--json", "as_json", is_flag=True, help="JSON output")
def callees(name: str, root: str | None, as_json: bool) -> None:
    """Show what a symbol calls."""
    root_path = _resolve_root(root)
    conn = _open_db(root_path)
    syms = find_symbol(conn, name)
    if not syms:
        conn.close()
        click.echo(f"Symbol '{name}' not found.", err=True)
        raise SystemExit(1)

    result = get_callees(conn, syms[0]["id"])
    conn.close()

    if as_json:
        click.echo(format_json(result))
        return

    if not result:
        click.echo(f"No callees found for '{name}'.")
        return

    click.echo(f"Callees of '{name}' ({len(result)}):")
    for item in result:
        location = (
            f"{item.get('file_path', '?')}:{item.get('line', '?')}"
            if item.get("file_path")
            else "unresolved"
        )
        click.echo(f"  {item['name']:<20s} {location}")


@cli.command()
@click.argument("name")
@click.option("--root", default=None, help="Project root")
@click.option("--kind", default=None, help="Filter by kind (function, class, method, variable)")
@click.option("--json", "as_json", is_flag=True, help="JSON output")
def symbol(name: str, root: str | None, kind: str | None, as_json: bool) -> None:
    """Find symbol definitions."""
    root_path = _resolve_root(root)
    conn = _open_db(root_path)
    results = find_symbol(conn, name, kind=kind)
    conn.close()

    if as_json:
        click.echo(format_json([dict(row) for row in results]))
        return

    if not results:
        click.echo(f"No symbols found matching '{name}'.")
        return

    for row in results:
        click.echo(f"  {row['kind']:<10s} {row['name']:<20s} {row['file_path']}:{row['line_start']}")
        if row["signature"]:
            click.echo(f"             {row['signature']}")


@cli.command("file")
@click.argument("path")
@click.option("--root", default=None, help="Project root")
@click.option("--json", "as_json", is_flag=True, help="JSON output")
def file_cmd(path: str, root: str | None, as_json: bool) -> None:
    """List all symbols in a file."""
    root_path = _resolve_root(root)
    conn = _open_db(root_path)
    normalized = path
    if Path(path).is_absolute():
        try:
            normalized = Path(path).resolve().relative_to(root_path).as_posix()
        except ValueError:
            normalized = Path(path).name
    results = list_file_symbols(conn, normalized)
    conn.close()

    if as_json:
        click.echo(format_json([dict(row) for row in results]))
        return

    if not results:
        click.echo(f"No symbols found in '{path}'. Is it indexed?")
        return

    click.echo(f"Symbols in {path}:")
    for row in results:
        click.echo(f"  {row['kind']:<10s} {row['name']:<20s} L{row['line_start']}-{row['line_end']}")


@cli.command()
@click.option("--root", default=None, help="Project root")
def stats(root: str | None) -> None:
    """Show index statistics."""
    root_path = _resolve_root(root)
    conn = _open_db(root_path)

    files = conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"]
    symbols = conn.execute("SELECT COUNT(*) AS c FROM symbols").fetchone()["c"]
    edges = conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"]
    resolved = conn.execute("SELECT COUNT(*) AS c FROM edges WHERE target_id IS NOT NULL").fetchone()["c"]
    langs = conn.execute(
        "SELECT language, COUNT(*) AS c FROM files GROUP BY language ORDER BY c DESC"
    ).fetchall()
    kinds = conn.execute(
        "SELECT kind, COUNT(*) AS c FROM symbols GROUP BY kind ORDER BY c DESC"
    ).fetchall()
    conn.close()

    click.echo(f"Index: {_db_path(root_path)}")
    click.echo(f"  Files:   {files}")
    click.echo(f"  Symbols: {symbols}")
    click.echo(f"  Edges:   {edges} ({resolved} resolved)")
    if langs:
        language_summary = ", ".join(f"{row['language']}({row['c']})" for row in langs)
        click.echo(f"  Languages: {language_summary}")
    if kinds:
        kind_summary = ", ".join(f"{row['kind']}({row['c']})" for row in kinds)
        click.echo(f"  Kinds: {kind_summary}")


@cli.command()
@click.argument("files", nargs=-1, required=True)
@click.option("--root", default=None, help="Project root")
def update(files: tuple[str, ...], root: str | None) -> None:
    """Re-index specific files (for git hooks)."""
    root_path = _resolve_root(root)
    conn = _open_db(root_path)

    indexed = 0
    for file_name in files:
        file_path = (root_path / file_name).resolve()
        if file_path.exists() and _is_indexable(file_path):
            indexed += _insert_file(conn, root_path, file_path)

    _resolve_edge_targets(conn)
    conn.close()
    click.echo(f"Updated {indexed}/{len(files)} files.")
