"""Tests for Go project context discovery."""

from pathlib import Path

from codebase_graph.indexer.go import project

FIXTURES = Path(__file__).parent / "fixtures" / "go"


def test_builds_package_import_paths_for_multi_module_repo():
    context = project.build_go_project_context(FIXTURES / "multi_module")

    app_context = context.for_file(
        FIXTURES / "multi_module" / "app" / "internal" / "util" / "util.go"
    )
    lib_context = context.for_file(
        FIXTURES / "multi_module" / "lib" / "pkg" / "math" / "math.go"
    )

    assert app_context.module_path == "example.com/app"
    assert app_context.package_import_path == "example.com/app/internal/util"
    assert app_context.package_name == "util"

    assert lib_context.module_path == "example.com/lib"
    assert lib_context.package_import_path == "example.com/lib/pkg/math"
    assert lib_context.package_name == "math"


def test_picks_owner_file_for_test_only_package():
    context = project.build_go_project_context(FIXTURES / "test_only")

    file_context = context.for_file(
        FIXTURES / "test_only" / "pkg" / "only_test_test.go"
    )

    assert file_context.is_package_owner is True
    assert file_context.package_import_path == "example.com/test-only/pkg"
