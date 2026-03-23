#!/usr/bin/env bash
set -euo pipefail

REPO="${CODEBASE_GRAPH_REPO:-humeo/codebase-graph}"
VERSION="${CODEBASE_GRAPH_VERSION:-}"
RELEASES_BASE="https://github.com/${REPO}/releases"

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

normalize_tag() {
  case "$1" in
    v*) printf '%s' "$1" ;;
    *) printf 'v%s' "$1" ;;
  esac
}

version_from_tag() {
  case "$1" in
    v*) printf '%s' "${1#v}" ;;
    *) printf '%s' "$1" ;;
  esac
}

latest_release_page_url() {
  printf '%s/latest' "$RELEASES_BASE"
}

latest_release_tag() {
  local page tag
  page="$(download "$(latest_release_page_url)")"
  tag="$(
    printf '%s' "$page" | tr '\n' ' ' | sed -n \
      's/.*property="og:url"[^>]*content="[^"]*\/releases\/tag\/\([^"]*\)".*/\1/p'
  )"

  if [ -z "$tag" ]; then
    tag="$(
      printf '%s' "$page" | tr '\n' ' ' | sed -n \
        's/.*<title>[[:space:]]*Release[[:space:]]\([^[:space:]<][^·<]*\)[[:space:]]·.*/\1/p'
    )"
  fi

  if [ -z "$tag" ]; then
    echo "Could not resolve latest release tag from GitHub." >&2
    exit 1
  fi

  printf '%s' "$tag"
}

resolved_release_tag() {
  if [ -n "$VERSION" ]; then
    normalize_tag "$VERSION"
    return
  fi

  latest_release_tag
}

wheel_filename() {
  printf 'codebase_graph-%s-py3-none-any.whl' "$(version_from_tag "$1")"
}

wheel_url() {
  local tag="$1"
  printf '%s/download/%s/%s' "$RELEASES_BASE" "$tag" "$(wheel_filename "$tag")"
}

main() {
  platform_name
  ensure_uv

  local tmpdir
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "${tmpdir:-}"' EXIT

  local tag asset_url wheel_path
  tag="$(resolved_release_tag)"
  asset_url="$(wheel_url "$tag")"
  wheel_path="$tmpdir/$(wheel_filename "$tag")"
  download_to_file "$asset_url" "$wheel_path"
  uv tool install --force "$wheel_path"
  echo "codebase-graph installed. Run 'cg --version' to verify."
}

main "$@"
