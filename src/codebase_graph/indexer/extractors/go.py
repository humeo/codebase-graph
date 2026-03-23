"""Go symbol extractor using tree-sitter."""

from tree_sitter import Tree


class GoExtractor:
    """Extract symbols and edges from Go source files."""

    def extract(self, tree: Tree, source: bytes, file_path: str, context=None):
        return [], []
