"""Go symbol extractor using tree-sitter."""

from dataclasses import dataclass
from typing import Protocol

from tree_sitter import Node, Tree

from codebase_graph.indexer.extractors.base import EdgeInfo, SymbolInfo


class _GoPackageContext(Protocol):
    package_name: str | None
    package_import_path: str | None


@dataclass
class _GoContext:
    package_name: str | None = None
    package_import_path: str | None = None


class GoExtractor:
    """Extract symbols and edges from Go source files."""

    def extract(
        self,
        tree: Tree,
        source: bytes,
        file_path: str,
        context: object | None = None,
    ) -> tuple[list[SymbolInfo], list[EdgeInfo]]:
        self._symbols: list[SymbolInfo] = []
        self._edges: list[EdgeInfo] = []
        self._source = source
        self._file_path = file_path
        self._context = self._normalize_context(context)
        self._package_prefix = (
            self._context.package_import_path or self._context.package_name
        )
        self._aliases: dict[str, str] = {}
        self._current_scope: str | None = None

        self._walk(tree.root_node)
        return self._symbols, self._edges

    def _walk(self, node: Node) -> None:
        if node.type == "import_declaration":
            self._extract_import(node)
            return

        if node.type == "type_declaration":
            self._extract_type_declaration(node)
            return

        if node.type == "function_declaration":
            self._extract_function(node)
            return

        if node.type == "method_declaration":
            self._extract_method(node)
            return

        for child in node.children:
            self._walk(child)

    def _extract_import(self, node: Node) -> None:
        scope = self._package_scope()
        line = node.start_point[0] + 1
        for child in self._iter_import_specs(node):

            import_path = self._import_path(child)
            if import_path is None:
                continue

            alias = self._import_alias(child, import_path)
            self._aliases[alias] = import_path
            self._edges.append(
                EdgeInfo(
                    source_name=scope,
                    target_name=import_path,
                    relation="imports",
                    line=line,
                )
            )

    def _iter_import_specs(self, node: Node) -> list[Node]:
        specs: list[Node] = []
        for child in node.children:
            if child.type == "import_spec":
                specs.append(child)
            elif child.type == "import_spec_list":
                specs.extend(self._iter_import_specs(child))
        return specs

    def _extract_type_declaration(self, node: Node) -> None:
        for child in node.children:
            if child.type == "type_spec":
                self._extract_type_spec(child)
            elif child.type == "type_alias":
                self._extract_type_alias(child)

    def _extract_type_spec(self, node: Node) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        name = self._text(name_node)
        qualified_name = self._qualify(name)
        self._symbols.append(
            SymbolInfo(
                name=name,
                qualified_name=qualified_name,
                kind="type",
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=self._signature(node),
                exported=name[:1].isupper(),
            )
        )

    def _extract_type_alias(self, node: Node) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return

        name = self._text(name_node)
        qualified_name = self._qualify(name)
        self._symbols.append(
            SymbolInfo(
                name=name,
                qualified_name=qualified_name,
                kind="type",
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=self._signature(node),
                exported=name[:1].isupper(),
            )
        )

    def _extract_function(self, node: Node) -> None:
        name_node = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        if name_node is None:
            return

        name = self._text(name_node)
        qualified_name = self._qualify(name)
        self._symbols.append(
            SymbolInfo(
                name=name,
                qualified_name=qualified_name,
                kind="function",
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=self._signature(node),
                exported=name[:1].isupper(),
            )
        )

        previous_scope = self._current_scope
        self._current_scope = qualified_name
        if body is not None:
            self._extract_calls(body)
        self._current_scope = previous_scope

    def _extract_method(self, node: Node) -> None:
        name_node = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        receiver = node.child_by_field_name("receiver")
        if name_node is None or receiver is None:
            return

        method_name = self._text(name_node)
        receiver_name = self._receiver_type_name(receiver)
        if receiver_name is None:
            return

        qualified_type = self._qualify(receiver_name)
        qualified_name = f"{qualified_type}.{method_name}"
        self._symbols.append(
            SymbolInfo(
                name=method_name,
                qualified_name=qualified_name,
                kind="method",
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=self._signature(node),
                exported=method_name[:1].isupper(),
            )
        )

        previous_scope = self._current_scope
        self._current_scope = qualified_name
        if body is not None:
            self._extract_calls(body)
        self._current_scope = previous_scope

    def _extract_calls(self, node: Node) -> None:
        if node.type == "call_expression":
            function_node = node.child_by_field_name("function")
            if function_node is not None:
                call_name = self._resolve_call_name(function_node)
                if call_name is not None:
                    self._edges.append(
                        EdgeInfo(
                            source_name=self._current_scope or self._package_scope(),
                            target_name=call_name,
                            relation="calls",
                            line=node.start_point[0] + 1,
                        )
                    )

        for child in node.children:
            if child.type in {
                "function_declaration",
                "method_declaration",
                "type_declaration",
                "import_declaration",
            }:
                continue
            self._extract_calls(child)

    def _resolve_call_name(self, node: Node) -> str | None:
        if node.type == "selector_expression":
            operand = node.child_by_field_name("operand")
            field = node.child_by_field_name("field")
            if operand is None or field is None:
                return None

            alias = self._text(operand)
            import_path = self._aliases.get(alias)
            if import_path is None:
                return None
            return f"{import_path}.{self._text(field)}"

        return None

    def _import_path(self, node: Node) -> str | None:
        for child in node.children:
            if child.type in {"interpreted_string_literal", "raw_string_literal"}:
                text = self._text(child)
                return text[1:-1]
        return None

    def _import_alias(self, node: Node, import_path: str) -> str:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return self._text(name_node)
        return import_path.rsplit("/", 1)[-1]

    def _receiver_type_name(self, node: Node) -> str | None:
        for child in node.children:
            if child.type != "parameter_declaration":
                continue
            type_node = child.child_by_field_name("type")
            if type_node is None:
                return None
            return self._type_name(type_node)
        return None

    def _type_name(self, node: Node) -> str | None:
        if node.type == "pointer_type":
            for child in node.children:
                name = self._type_name(child)
                if name is not None:
                    return name
        if node.type in {"type_identifier", "identifier"}:
            return self._text(node)
        return None

    def _qualify(self, name: str) -> str:
        if self._package_prefix is None:
            return name
        return f"{self._package_prefix}.{name}"

    def _package_scope(self) -> str:
        return "__module__"

    def _signature(self, node: Node) -> str | None:
        text = self._source[node.start_byte : node.end_byte].decode("utf-8").strip()
        return text or None

    def _normalize_context(self, context: _GoPackageContext | object | None) -> _GoContext:
        if context is None:
            return _GoContext()

        return _GoContext(
            package_name=getattr(context, "package_name", None),
            package_import_path=getattr(context, "package_import_path", None),
        )

    @staticmethod
    def _text(node: Node) -> str:
        return node.text.decode("utf-8")
