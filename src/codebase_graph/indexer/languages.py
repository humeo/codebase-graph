"""Language registry for tree-sitter languages and extractors."""

from tree_sitter import Language
import tree_sitter_python as tspython

from codebase_graph.indexer.extractors.python import PythonExtractor

_REGISTRY: dict[str, tuple[Language, type[PythonExtractor]]] = {}


def _init_registry() -> None:
    global _REGISTRY
    if _REGISTRY:
        return
    _REGISTRY = {
        ".py": (Language(tspython.language()), PythonExtractor),
    }


def get_language_and_extractor(suffix: str) -> tuple[Language | None, object | None]:
    """Return the language and extractor instance for a file suffix."""
    _init_registry()
    entry = _REGISTRY.get(suffix)
    if entry is None:
        return None, None
    language, extractor_cls = entry
    return language, extractor_cls()


def register_language(
    suffix: str, language: Language, extractor_cls: type[PythonExtractor]
) -> None:
    """Register a new language extractor."""
    _init_registry()
    _REGISTRY[suffix] = (language, extractor_cls)


def supported_suffixes() -> set[str]:
    """Return all supported file suffixes."""
    _init_registry()
    return set(_REGISTRY)
