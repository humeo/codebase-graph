"""Language registry for tree-sitter languages and extractors."""

from typing import Any

from tree_sitter import Language
import tree_sitter_python as tspython

from codebase_graph.indexer.extractors.python import PythonExtractor

_REGISTRY: dict[str, tuple[str, Language, type[Any]]] = {}


def _init_registry() -> None:
    global _REGISTRY
    if _REGISTRY:
        return
    _REGISTRY = {
        ".py": ("python", Language(tspython.language()), PythonExtractor),
    }


def get_language_and_extractor(suffix: str) -> tuple[Language | None, object | None]:
    """Return the language and extractor instance for a file suffix."""
    _init_registry()
    entry = _REGISTRY.get(suffix)
    if entry is None:
        return None, None
    _, language, extractor_cls = entry
    return language, extractor_cls()


def register_language(
    suffix: str, language_name: str, language: Language, extractor_cls: type[Any]
) -> None:
    """Register a new language extractor."""
    _init_registry()
    _REGISTRY[suffix] = (language_name, language, extractor_cls)


def get_language_name(suffix: str) -> str | None:
    """Return the registered language name for a file suffix."""
    _init_registry()
    entry = _REGISTRY.get(suffix)
    if entry is None:
        return None
    return entry[0]


def supported_suffixes() -> set[str]:
    """Return all supported file suffixes."""
    _init_registry()
    return set(_REGISTRY)
