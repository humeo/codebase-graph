#!/usr/bin/env bash
set -euo pipefail

REPO="${CODEBASE_GRAPH_REPO:-humeo/codebase-graph}"
VERSION="${CODEBASE_GRAPH_VERSION:-}"
API_BASE="https://api.github.com/repos/${REPO}/releases"

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

platform_name() {
  case "$(uname -s)" in
    Linux | Darwin) return 0 ;;
    *)
      echo "Unsupported platform: $(uname -s). Only Linux and macOS are supported." >&2
      exit 1
      ;;
  esac
}

download() {
  if need_cmd curl; then
    curl -fsSL "$@"
    return
  fi
  if need_cmd wget; then
    wget -qO- "$1"
    return
  fi
  echo "Either curl or wget is required." >&2
  exit 1
}

download_to_file() {
  local url="$1"
  local out="$2"

  if need_cmd curl; then
    curl -fsSL "$url" -o "$out"
    return
  fi

  wget -qO "$out" "$url"
}

ensure_uv() {
  if need_cmd uv; then
    return
  fi
  if ! need_cmd curl && ! need_cmd wget; then
    echo "uv is missing and either curl or wget is required to bootstrap it." >&2
    exit 1
  fi

  download "https://astral.sh/uv/install.sh" | sh
  export PATH="$HOME/.local/bin:$PATH"

  if ! need_cmd uv; then
    echo "uv installation completed but uv was not found on PATH." >&2
    exit 1
  fi
}

release_url() {
  if [ -z "$VERSION" ]; then
    printf '%s/latest' "$API_BASE"
    return
  fi

  case "$VERSION" in
    v*) printf '%s/tags/%s' "$API_BASE" "$VERSION" ;;
    *) printf '%s/tags/v%s' "$API_BASE" "$VERSION" ;;
  esac
}

select_wheel_urls() {
  tr '\n' ' ' | sed 's/},[[:space:]]*{/}\n{/g' | while IFS= read -r asset || [ -n "$asset" ]; do
    name="$(printf '%s' "$asset" | sed -n 's/.*"name":"\([^"]*\)".*/\1/p')"
    url="$(printf '%s' "$asset" | sed -n 's/.*"browser_download_url":"\([^"]*\)".*/\1/p')"

    case "$name" in
      codebase_graph-*-py3-none-any.whl)
        if [ -n "$url" ]; then
          printf '%s\n' "$url"
        fi
        ;;
    esac
  done
}

main() {
  platform_name
  ensure_uv

  local tmpdir
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "${tmpdir:-}"' EXIT

  local release_json wheel_matches wheel_url wheel_path match_count
  release_json="$(download "$(release_url)")"
  wheel_matches="$(printf '%s' "$release_json" | select_wheel_urls)"
  match_count="$(printf '%s\n' "$wheel_matches" | sed '/^$/d' | wc -l | tr -d ' ')"

  if [ "$match_count" -eq 0 ]; then
    echo "No wheel asset found in GitHub release metadata." >&2
    exit 1
  fi
  if [ "$match_count" -ne 1 ]; then
    echo "Expected exactly one wheel asset in GitHub release metadata." >&2
    exit 1
  fi

  wheel_url="$wheel_matches"

  wheel_path="$tmpdir/codebase-graph.whl"
  download_to_file "$wheel_url" "$wheel_path"
  uv tool install --force "$wheel_path"
  echo "codebase-graph installed. Run 'cg --version' to verify."
}

main "$@"
