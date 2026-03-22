"""Output formatting for query results."""

import json


def format_context_text(result: dict) -> str:
    """Format context query result as human-readable text."""
    symbol = result["symbol"]
    lines = []

    lines.append(f"── Symbol: {symbol['name']} {'─' * max(1, 50 - len(symbol['name']))}")
    lines.append(f"  Kind:      {symbol['kind']}")
    lines.append(
        f"  File:      {symbol['file']}:{symbol['line_start']}-{symbol['line_end']}"
    )
    if symbol.get("signature"):
        lines.append(f"  Signature: {symbol['signature']}")

    callers = result.get("callers", [])
    if callers:
        lines.append(f"\n── Called by ({len(callers)}) {'─' * 40}")
        for caller in callers:
            loc = f"{caller.get('file_path', '?')}:{caller.get('line', '?')}"
            lines.append(f"  {caller['name']:<25s} {loc}")

    callees = result.get("callees", [])
    if callees:
        lines.append(f"\n── Calls ({len(callees)}) {'─' * 43}")
        for callee in callees:
            loc = (
                f"{callee.get('file_path', '?')}:{callee.get('line', '?')}"
                if callee.get("file_path")
                else "unresolved"
            )
            lines.append(f"  {callee['name']:<25s} {loc}")

    key_files = result.get("key_files", [])
    if key_files:
        lines.append(f"\n── Key Files {'─' * 42}")
        for file_info in key_files:
            lines.append(f"  {file_info['path']}")

    return "\n".join(lines)


def format_json(data: dict | list) -> str:
    """Format any data as JSON."""
    return json.dumps(data, indent=2, default=str)
