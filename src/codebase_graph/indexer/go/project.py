"""Project context helpers for Go codebases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


_MODULE_RE = re.compile(r"^module\s+(\S+)\s*$")
_PACKAGE_RE = re.compile(r"^package\s+([A-Za-z_][A-Za-z0-9_]*)\s*$")


@dataclass(frozen=True)
class GoFileContext:
    module_root: Path
    module_path: str
    package_name: str
    package_import_path: str
    is_package_owner: bool


@dataclass(frozen=True)
class _Module:
    root: Path
    path: str


class GoProjectContext:
    """Lookup table for Go file metadata within a project."""

    def __init__(self, file_contexts: dict[Path, GoFileContext]) -> None:
        self._file_contexts = file_contexts

    def for_file(self, path: Path) -> GoFileContext:
        return self._file_contexts[path.resolve()]


def build_go_project_context(root: Path) -> GoProjectContext:
    root = root.resolve()
    modules = _discover_modules(root)
    package_files: dict[tuple[Path, str], list[Path]] = {}
    file_details: dict[Path, tuple[_Module, str, Path]] = {}

    for file_path in sorted(root.rglob("*.go")):
        resolved = file_path.resolve()
        module = _select_module(resolved, modules)
        package_name = _parse_package_name(resolved)
        package_dir = resolved.parent
        file_details[resolved] = (module, package_name, package_dir)
        package_files.setdefault((package_dir, package_name), []).append(resolved)

    owners = {
        key: _select_owner_file(files)
        for key, files in package_files.items()
    }

    file_contexts: dict[Path, GoFileContext] = {}
    for file_path, (module, package_name, package_dir) in file_details.items():
        relative_dir = package_dir.relative_to(module.root)
        package_import_path = module.path
        if relative_dir.parts:
            package_import_path = f"{module.path}/{'/'.join(relative_dir.parts)}"

        file_contexts[file_path] = GoFileContext(
            module_root=module.root,
            module_path=module.path,
            package_name=package_name,
            package_import_path=package_import_path,
            is_package_owner=file_path == owners[(package_dir, package_name)],
        )

    return GoProjectContext(file_contexts)


def _discover_modules(root: Path) -> list[_Module]:
    modules: list[_Module] = []
    for mod_file in sorted(root.rglob("go.mod")):
        module_root = mod_file.parent.resolve()
        modules.append(_Module(root=module_root, path=_parse_module_path(mod_file)))
    return modules


def _select_module(file_path: Path, modules: list[_Module]) -> _Module:
    candidates = [module for module in modules if module.root in file_path.parents]
    if not candidates:
        raise KeyError(f"No go.mod found for {file_path}")
    return max(candidates, key=lambda module: len(module.root.parts))


def _select_owner_file(files: list[Path]) -> Path:
    non_test_files = [path for path in files if not path.name.endswith("_test.go")]
    return min(non_test_files or files, key=lambda path: path.name)


def _parse_module_path(mod_file: Path) -> str:
    return _parse_directive(mod_file.read_text(encoding="utf-8"), _MODULE_RE, mod_file)


def _parse_package_name(go_file: Path) -> str:
    return _parse_directive(go_file.read_text(encoding="utf-8"), _PACKAGE_RE, go_file)


def _parse_directive(contents: str, pattern: re.Pattern[str], path: Path) -> str:
    in_block_comment = False
    for raw_line in contents.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if in_block_comment:
            if "*/" in line:
                in_block_comment = False
                _, _, line = line.partition("*/")
                line = line.strip()
                if not line:
                    continue
            else:
                continue

        while line.startswith("/*"):
            _, _, remainder = line.partition("/*")
            if "*/" not in remainder:
                in_block_comment = True
                line = ""
                break
            _, _, remainder = remainder.partition("*/")
            line = remainder.strip()
        if not line or line.startswith("//"):
            continue

        match = pattern.match(line)
        if match:
            return match.group(1)

    raise ValueError(f"Could not parse directive from {path}")
