"""Tests for git hook installation helpers."""

from pathlib import Path

from codebase_graph.hooks import HOOK_MARKER, install_hook, uninstall_hook


def _read_hook(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_install_hook_creates_post_commit_hook(tmp_path):
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)

    installed = install_hook(tmp_path)

    hook_path = hooks_dir / "post-commit"
    assert installed is True
    assert hook_path.exists()
    assert HOOK_MARKER in _read_hook(hook_path)
    assert hook_path.stat().st_mode & 0o111


def test_install_hook_is_idempotent(tmp_path):
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)

    assert install_hook(tmp_path) is True
    assert install_hook(tmp_path) is False


def test_uninstall_hook_removes_installed_hook(tmp_path):
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    hook_path = hooks_dir / "post-commit"

    assert install_hook(tmp_path) is True
    assert uninstall_hook(tmp_path) is True
    assert not hook_path.exists()


def test_install_hook_supports_worktree_git_file(tmp_path):
    git_dir = tmp_path / "repo.git"
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True)

    worktree_root = tmp_path / "worktree"
    worktree_root.mkdir()
    (worktree_root / ".git").write_text(f"gitdir: {git_dir}\n", encoding="utf-8")

    installed = install_hook(worktree_root)

    hook_path = hooks_dir / "post-commit"
    assert installed is True
    assert hook_path.exists()
    assert HOOK_MARKER in _read_hook(hook_path)
