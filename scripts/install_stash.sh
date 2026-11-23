#!/usr/bin/env bash
# Download a Stash release binary into ./bin/stash.
# Usage: install_stash.sh [version]   (version like v0.29.3, or "latest"; default from STASH_VERSION file)
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
version="${1:-$(tr -d '[:space:]' < "$root/STASH_VERSION")}"

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)          asset=stash-linux ;;
  Linux-aarch64|Linux-arm64) asset=stash-linux-arm64v8 ;;
  Darwin-*)              asset=stash-macos ;;
  # Windows on ARM runs the x64 build under emulation.
  MINGW*|MSYS*|CYGWIN*)  asset=stash-win.exe ;;
  *) echo "unsupported platform $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac

if [[ "$version" == "latest" ]]; then
  url="https://github.com/stashapp/stash/releases/latest/download/$asset"
else
  url="https://github.com/stashapp/stash/releases/download/$version/$asset"
fi

mkdir -p "$root/bin"
echo "downloading $url"
exe="$root/bin/stash"
[[ "$asset" == *.exe ]] && exe="$exe.exe"  # MSYS still runs it as bin/stash
curl -fsSL --retry 3 -o "$exe" "$url"
chmod +x "$exe"
echo "installed $("$root/bin/stash" --version 2>/dev/null | head -1 || echo "$asset ($version)")"
