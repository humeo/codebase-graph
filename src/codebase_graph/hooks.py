"""Git hook installation for automatic index updates."""

from pathlib import Path
import subprocess

HOOK_MARKER = "# codebase-graph:"
HOOK_START = f"{HOOK_MARKER} start"
HOOK_END = f"{HOOK_MARKER} end"
HOOK_SNIPPET = f"""\
{HOOK_START}
changed_files=$(git diff-tree --no-commit-id --name-only -r HEAD)
repo_root=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -n "$changed_files" ] && [ -n "$repo_root" ]; then
    cg update --root "$repo_root" $changed_files 2>/dev/null || true
fi
{HOOK_END}
"""


def _resolve_git_dir(root: Path) -> Path | None:
    git_path = root / ".git"
    if git_path.is_dir():
        return git_path

    if git_path.is_file():
        content = git_path.read_text(encoding="utf-8").strip()
        prefix = "gitdir:"
        if content.startswith(prefix):
            target = content[len(prefix) :].strip()
            git_dir = Path(target)
            if not git_dir.is_absolute():
                git_dir = (root / git_dir).resolve()
            return git_dir

    return None


def _resolve_hooks_dir(root: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        hooks_dir = Path(result.stdout.strip())
        if not hooks_dir.is_absolute():
            hooks_dir = (root / hooks_dir).resolve()
        return hooks_dir

    git_dir = _resolve_git_dir(root)
    if git_dir is None:
        return None
    return git_dir / "hooks"


def install_hook(root: Path) -> bool:
    """Install post-commit hook. Returns True if installed."""
    hooks_dir = _resolve_hooks_dir(root)
    if hooks_dir is None:
        return False

    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "post-commit"

    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8")
        if HOOK_START in existing:
            return False
        updated = existing.rstrip() + "\n\n" + HOOK_SNIPPET
    else:
        updated = "#!/bin/sh\n" + HOOK_SNIPPET

    hook_path.write_text(updated, encoding="utf-8")
    hook_path.chmod(0o755)
    return True


def uninstall_hook(root: Path) -> bool:
    """Remove the codebase-graph post-commit hook. Returns True if removed."""
    hooks_dir = _resolve_hooks_dir(root)
    if hooks_dir is None:
        return False

    hook_path = hooks_dir / "post-commit"
    if not hook_path.exists():
        return False

    content = hook_path.read_text(encoding="utf-8")
    start = content.find(HOOK_START)
    end = content.find(HOOK_END)
    if start == -1 or end == -1 or end < start:
        return False

    end += len(HOOK_END)
    before = content[:start].rstrip()
    after = content[end:].lstrip()
    remaining_parts = [part for part in (before, after) if part]
    remaining = "\n\n".join(remaining_parts).strip()

    if remaining in {"", "#!/bin/sh"}:
        hook_path.unlink()
        return True

    hook_path.write_text(remaining + "\n", encoding="utf-8")
    hook_path.chmod(0o755)
    return True
