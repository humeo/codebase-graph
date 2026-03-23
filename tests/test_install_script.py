"""Tests for the public install script."""

from pathlib import Path
import os
import shutil
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "install.sh"


def _write_fake_bin(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _link_system_bin(bin_dir: Path, name: str) -> None:
    target = shutil.which(name)
    if target is None:
        raise AssertionError(f"Required system command not found: {name}")
    (bin_dir / name).symlink_to(target)


def _run_install(
    tmp_path,
    *,
    release_json: str,
    version: str | None = None,
    with_curl: bool = True,
    with_wget: bool = False,
    with_uv: bool = True,
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "calls.log"

    for name in ("awk", "chmod", "mkdir", "mktemp", "rm", "sed", "sh", "tr", "wc"):
        _link_system_bin(bin_dir, name)

    if with_curl:
        _write_fake_bin(
            bin_dir,
            "curl",
            textwrap.dedent(
                f"""\
                #!/bin/sh
                echo "curl:$*" >> "{log_path}"
                case "$*" in
                  *api.github.com*)
                    printf '%s' '{release_json}'
                    ;;
                  *example.test*|*releases/download*)
                    out=""
                    while [ "$#" -gt 0 ]; do
                      if [ "$1" = "-o" ]; then
                        out="$2"
                        shift 2
                        continue
                      fi
                      shift
                    done
                    printf 'wheel' > "$out"
                    ;;
                  *astral.sh/uv/install.sh*)
                    printf '#!/bin/sh\\nmkdir -p "$HOME/.local/bin"\\nprintf '"'"'#!/bin/sh\\\\nexit 0\\\\n'"'"' > "$HOME/.local/bin/uv"\\nchmod +x "$HOME/.local/bin/uv"\\n'
                    ;;
                esac
                """
            ),
        )
    if with_wget:
        _write_fake_bin(
            bin_dir,
            "wget",
            textwrap.dedent(
                f"""\
                #!/bin/sh
                echo "wget:$*" >> "{log_path}"
                case "$*" in
                  *api.github.com*)
                    printf '%s' '{release_json}'
                    ;;
                  *example.test*|*releases/download*)
                    if [ "$1" = "-qO" ]; then
                      printf 'wheel' > "$2"
                    fi
                    ;;
                  *astral.sh/uv/install.sh*)
                    printf '#!/bin/sh\\nmkdir -p "$HOME/.local/bin"\\nprintf '"'"'#!/bin/sh\\\\nexit 0\\\\n'"'"' > "$HOME/.local/bin/uv"\\nchmod +x "$HOME/.local/bin/uv"\\n'
                    ;;
                esac
                """
            ),
        )
    _write_fake_bin(
        bin_dir,
        "uname",
        """#!/bin/sh
printf 'Linux\\n'
""",
    )
    if with_uv:
        _write_fake_bin(
            bin_dir,
            "uv",
            textwrap.dedent(
                f"""\
                #!/bin/sh
                echo "uv:$*" >> "{log_path}"
                exit 0
                """
            ),
        )

    env = os.environ.copy()
    env["PATH"] = str(bin_dir)
    env["HOME"] = str(tmp_path)
    if version is not None:
        env["CODEBASE_GRAPH_VERSION"] = version

    result = subprocess.run(
        ["/bin/bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    calls = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    return result, calls


def test_install_script_uses_latest_release_when_version_unset(tmp_path):
    result, calls = _run_install(
        tmp_path,
        release_json='{"assets":[{"name":"codebase_graph-0.1.0-py3-none-any.whl","browser_download_url":"https://example.test/v0.1.0/codebase_graph-0.1.0-py3-none-any.whl"}]}',
    )

    assert result.returncode == 0
    assert "releases/latest" in calls
    assert "https://example.test/v0.1.0/codebase_graph-0.1.0-py3-none-any.whl" in calls
    assert "uv:tool install --force" in calls


def test_install_script_normalizes_explicit_version(tmp_path):
    result, calls = _run_install(
        tmp_path,
        release_json='{"assets":[{"name":"codebase_graph-0.1.0-py3-none-any.whl","browser_download_url":"https://example.test/v0.1.0/codebase_graph-0.1.0-py3-none-any.whl"}]}',
        version="0.1.0",
    )

    assert result.returncode == 0
    assert "releases/tags/v0.1.0" in calls


def test_install_script_handles_reversed_asset_field_order(tmp_path):
    result, calls = _run_install(
        tmp_path,
        release_json='{"assets":[{"browser_download_url":"https://example.test/v0.1.0/codebase_graph-0.1.0-py3-none-any.whl","name":"codebase_graph-0.1.0-py3-none-any.whl"}]}',
    )

    assert result.returncode == 0
    assert "https://example.test/v0.1.0/codebase_graph-0.1.0-py3-none-any.whl" in calls


def test_install_script_fails_without_matching_wheel(tmp_path):
    result, _calls = _run_install(
        tmp_path,
        release_json='{"assets":[{"name":"codebase_graph-0.1.0.tar.gz","browser_download_url":"https://example.test/v0.1.0/codebase_graph-0.1.0.tar.gz"}]}',
    )

    assert result.returncode == 1
    assert "No wheel asset found" in result.stderr


def test_install_script_fails_with_duplicate_matching_wheels(tmp_path):
    result, _calls = _run_install(
        tmp_path,
        release_json='{"assets":[{"name":"codebase_graph-0.1.0-py3-none-any.whl","browser_download_url":"https://example.test/v0.1.0/codebase_graph-0.1.0-py3-none-any.whl"},{"name":"codebase_graph-0.1.0+mirror-py3-none-any.whl","browser_download_url":"https://example.test/v0.1.0/codebase_graph-0.1.0+mirror-py3-none-any.whl"}]}',
    )

    assert result.returncode == 1
    assert "Expected exactly one wheel asset" in result.stderr


def test_install_script_fails_on_unsupported_platform(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uname").write_text("#!/bin/sh\nprintf 'FreeBSD\\n'\n", encoding="utf-8")
    (bin_dir / "uname").chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = subprocess.run(
        ["/bin/bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Unsupported platform" in result.stderr


def test_install_script_bootstraps_uv_with_wget_only(tmp_path):
    result, calls = _run_install(
        tmp_path,
        release_json='{"assets":[{"name":"codebase_graph-0.1.0-py3-none-any.whl","browser_download_url":"https://example.test/v0.1.0/codebase_graph-0.1.0-py3-none-any.whl"}]}',
        with_curl=False,
        with_wget=True,
        with_uv=False,
    )

    assert result.returncode == 0
    assert "wget:-qO- https://astral.sh/uv/install.sh" in calls
