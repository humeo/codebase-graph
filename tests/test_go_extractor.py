"""Tests for Go symbol extraction."""

from pathlib import Path
from types import SimpleNamespace

import tree_sitter_go as tsgo
from tree_sitter import Language, Parser

from codebase_graph.indexer.extractors.go import GoExtractor

FIXTURES = Path(__file__).parent / "fixtures" / "go"


def _parse(path: Path, context=None):
    parser = Parser(Language(tsgo.language()))
    source = path.read_bytes()
    tree = parser.parse(source)
    extractor = GoExtractor()
    return extractor.extract(tree, source, str(path), context=context)


def test_extracts_go_functions_methods_and_types():
    symbols, _ = _parse(
        FIXTURES / "basic" / "internal" / "util" / "util.go",
        context=SimpleNamespace(
            package_name="util",
            package_import_path="example.com/basic/internal/util",
        ),
    )

    qualified = {(symbol.kind, symbol.qualified_name) for symbol in symbols}
    assert ("function", "example.com/basic/internal/util.Parse") in qualified
    assert ("method", "example.com/basic/internal/util.Service.Run") in qualified
    assert ("type", "example.com/basic/internal/util.Service") in qualified


def test_extracts_go_import_edges_and_alias_selector_calls():
    _, edges = _parse(
        FIXTURES / "basic" / "main.go",
        context=SimpleNamespace(
            package_name="main",
            package_import_path="example.com/basic",
        ),
    )

    imports = {(edge.relation, edge.target_name) for edge in edges if edge.relation == "imports"}
    calls = {(edge.relation, edge.target_name) for edge in edges if edge.relation == "calls"}

    assert ("imports", "example.com/basic/internal/util") in imports
    assert ("calls", "example.com/basic/internal/util.Parse") in calls
