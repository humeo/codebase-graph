"""Tests for Python symbol extraction."""

from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

from codebase_graph.indexer.extractors.base import EdgeInfo, SymbolInfo
from codebase_graph.indexer.extractors.python import PythonExtractor

FIXTURES = Path(__file__).parent / "fixtures" / "python"


def _parse(path: Path) -> tuple[list[SymbolInfo], list[EdgeInfo]]:
    parser = Parser(Language(tspython.language()))
    source = path.read_bytes()
    tree = parser.parse(source)
    extractor = PythonExtractor()
    return extractor.extract(tree, source, str(path))


def test_extracts_functions():
    symbols, _ = _parse(FIXTURES / "main.py")
    func_names = {s.name for s in symbols if s.kind == "function"}
    assert "process_payment" in func_names


def test_extracts_classes():
    symbols, _ = _parse(FIXTURES / "models.py")
    class_names = {s.name for s in symbols if s.kind == "class"}
    assert "Order" in class_names
    assert "Receipt" in class_names


def test_extracts_methods():
    symbols, _ = _parse(FIXTURES / "models.py")
    method_names = {s.name for s in symbols if s.kind == "method"}
    assert "validate" in method_names
    assert "__init__" in method_names


def test_extracts_import_edges():
    _, edges = _parse(FIXTURES / "main.py")
    import_targets = {e.target_name for e in edges if e.relation == "imports"}
    assert "Order" in import_targets
    assert "validate_order" in import_targets
    assert "format_currency" in import_targets


def test_extracts_call_edges():
    _, edges = _parse(FIXTURES / "main.py")
    call_targets = {e.target_name for e in edges if e.relation == "calls"}
    assert "validate_order" in call_targets
    assert "format_currency" in call_targets


def test_extracts_inherits_edges():
    symbols, edges = _parse(FIXTURES / "models.py")
    assert symbols
    inherits = [e for e in edges if e.relation == "inherits"]
    assert len(inherits) == 0


def test_captures_signature():
    symbols, _ = _parse(FIXTURES / "main.py")
    process = next(s for s in symbols if s.name == "process_payment")
    assert "order: Order" in process.signature
    assert "Receipt" in process.signature
