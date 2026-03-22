"""The core `context` query -- compressed navigation for a symbol."""

import sqlite3
from collections import Counter

from codebase_graph.query.relations import get_callees, get_callers, get_imports
from codebase_graph.query.symbols import find_symbol


def query_context(
    conn: sqlite3.Connection, name: str, depth: int = 1
) -> dict | None:
    """Return compressed context for a symbol."""
    del depth

    matches = find_symbol(conn, name)
    if not matches:
        return None

    symbol = matches[0]
    for match in matches:
        if match["kind"] in ("function", "class"):
            symbol = match
            break

    symbol_id = symbol["id"]
    callers = get_callers(conn, symbol_id)
    callees = get_callees(conn, symbol_id)
    imports = get_imports(conn, symbol_id)

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
        for path, score in file_scores.most_common(5)
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
        "imports": imports,
        "key_files": key_files,
    }
