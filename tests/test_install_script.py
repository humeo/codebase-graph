"""Tests for the public install script."""

from pathlib import Path
import os
import shutil
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "install.sh"
LATEST_RELEASE_PAGE = textwrap.dedent(
    """\
    <html>
      <head>
        <meta property="og:url" content="/humeo/codebase-graph/releases/tag/v0.1.0" />
        <title>Release v0.1.0 · humeo/codebase-graph · GitHub</title>
      </head>
    </html>
    """
)


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
    release_page_html: str = LATEST_RELEASE_PAGE,
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
                    echo "unexpected api call" >&2
                    exit 22
                    ;;
                  *github.com*releases/latest*|*github.com*releases/tag/*)
                    printf '%s' '{release_page_html}'
                    ;;
                  *releases/download*)
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
                    echo "unexpected api call" >&2
                    exit 1
                    ;;
                  *github.com*releases/latest*|*github.com*releases/tag/*)
                    printf '%s' '{release_page_html}'
                    ;;
                  *releases/download*)
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
    )

    assert result.returncode == 0
    assert "github.com/humeo/codebase-graph/releases/latest" in calls
    assert "api.github.com" not in calls
    assert (
        "https://github.com/humeo/codebase-graph/releases/download/v0.1.0/"
        "codebase_graph-0.1.0-py3-none-any.whl"
    ) in calls
    assert "uv:tool install --force" in calls


def test_install_script_preserves_wheel_filename_for_uv(tmp_path):
    result, calls = _run_install(tmp_path)

    assert result.returncode == 0
    uv_call = next(line for line in calls.splitlines() if line.startswith("uv:tool install --force "))
    assert uv_call.endswith("/codebase_graph-0.1.0-py3-none-any.whl")


def test_install_script_normalizes_explicit_version(tmp_path):
    result, calls = _run_install(
        tmp_path,
        version="0.1.0",
    )

    assert result.returncode == 0
    assert "releases/latest" not in calls
    assert (
        "https://github.com/humeo/codebase-graph/releases/download/v0.1.0/"
        "codebase_graph-0.1.0-py3-none-any.whl"
    ) in calls


def test_install_script_accepts_prefixed_explicit_version(tmp_path):
    result, calls = _run_install(
        tmp_path,
        version="v0.1.0",
    )

    assert result.returncode == 0
    assert (
        "https://github.com/humeo/codebase-graph/releases/download/v0.1.0/"
        "codebase_graph-0.1.0-py3-none-any.whl"
    ) in calls


def test_install_script_uses_title_fallback_when_og_url_is_missing(tmp_path):
    result, calls = _run_install(
        tmp_path,
        release_page_html=textwrap.dedent(
            """\
            <html>
              <head>
                <title>Release v0.2.0 · humeo/codebase-graph · GitHub</title>
              </head>
            </html>
            """
        ),
    )

    assert result.returncode == 0
    assert (
        "https://github.com/humeo/codebase-graph/releases/download/v0.2.0/"
        "codebase_graph-0.2.0-py3-none-any.whl"
    ) in calls


def test_install_script_fails_when_latest_release_tag_cannot_be_resolved(tmp_path):
    result, _calls = _run_install(
        tmp_path,
        release_page_html="<html><head><title>Releases</title></head></html>",
    )

    assert result.returncode == 1
    assert "Could not resolve latest release tag from GitHub." in result.stderr


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
        with_curl=False,
        with_wget=True,
        with_uv=False,
    )

    assert result.returncode == 0
    assert "wget:-qO- https://astral.sh/uv/install.sh" in calls
