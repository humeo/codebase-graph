"""Indexer engine for parsing files and storing symbols and edges."""

import hashlib
import logging
import sqlite3
from pathlib import Path

from tree_sitter import Parser

from codebase_graph.indexer.languages import get_language_and_extractor, supported_suffixes
from codebase_graph.storage.db import (
    delete_file_data,
    get_file_by_path,
    insert_edge,
    insert_symbol,
    resolve_edges,
    upsert_file,
)

log = logging.getLogger(__name__)

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".codebase-graph",
    ".next",
    ".nuxt",
}


def _content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _language_for_file(path: Path) -> str | None:
    return {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
    }.get(path.suffix)


def index_file(conn: sqlite3.Connection, file_path: Path, root: Path) -> bool:
    """Index a single file and return whether it was reindexed."""
    rel_path = str(file_path.relative_to(root))
    language = _language_for_file(file_path)
    if language is None:
        return False

    language_obj, extractor = get_language_and_extractor(file_path.suffix)
    if language_obj is None or extractor is None:
        return False

    source = file_path.read_bytes()
    content_hash = _content_hash(source)

    existing = get_file_by_path(conn, rel_path)
    if existing is not None and existing["content_hash"] == content_hash:
        log.debug("Skipping unchanged file: %s", rel_path)
        return False

    parser = Parser(language_obj)
    tree = parser.parse(source)
    symbols, edges = extractor.extract(tree, source, rel_path)

    file_id = upsert_file(conn, rel_path, language, content_hash)
    delete_file_data(conn, file_id)

    symbol_id_map: dict[str, int] = {}
    for symbol in symbols:
        symbol_id = insert_symbol(
            conn,
            name=symbol.name,
            qualified_name=symbol.qualified_name,
            kind=symbol.kind,
            file_id=file_id,
            line_start=symbol.line_start,
            line_end=symbol.line_end,
            signature=symbol.signature,
            exported=symbol.exported,
        )
        if symbol.qualified_name:
            symbol_id_map[symbol.qualified_name] = symbol_id
        symbol_id_map[symbol.name] = symbol_id

    for edge in edges:
        source_id = symbol_id_map.get(edge.source_name)
        if source_id is None:
            for key, symbol_id in symbol_id_map.items():
                if key == edge.source_name or key.endswith(f".{edge.source_name}"):
                    source_id = symbol_id
                    break
        if source_id is None:
            log.debug("Skipping edge with unknown source %s", edge.source_name)
            continue
        insert_edge(conn, source_id, edge.target_name, edge.relation, file_id, edge.line)

    log.debug(
        "Indexed %s with %d symbols and %d edges", rel_path, len(symbols), len(edges)
    )
    return True


def index_directory(conn: sqlite3.Connection, root: Path) -> dict[str, int]:
    """Index all supported files below root and resolve cross-file edges."""
    root = root.resolve()
    stats = {"files_scanned": 0, "files_indexed": 0, "files_skipped": 0}

    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix not in supported_suffixes():
            continue

        stats["files_scanned"] += 1
        if index_file(conn, path, root):
            stats["files_indexed"] += 1
        else:
            stats["files_skipped"] += 1

    stats["edges_resolved"] = resolve_edges(conn)
    return stats
