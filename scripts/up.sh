#!/usr/bin/env bash
# One-shot local bring-up: generate media, install + start Stash, seed, verify.
# Usage: up.sh [data-dir] [port]
# Writes credentials to ./stash-test-server.env
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
data_dir="${1:-$root/.stash-data}"
port="${2:-9999}"

python3 "$root/scripts/generate_media.py" --out "$root/media"
[[ -x "$root/bin/stash" ]] || "$root/scripts/install_stash.sh"
"$root/scripts/start_stash.sh" "$data_dir" "$port"
data_dir="$(cd "$data_dir" && pwd)"

if ! python3 "$root/scripts/seed.py" \
      --url "http://127.0.0.1:$port" \
      --server-data-dir "$data_dir" \
      --server-library-dir "$root/media/library" \
      --env-out "$root/stash-test-server.env"; then
  echo "--- last 80 lines of stash.log ---" >&2
  tail -n 80 "$data_dir/stash.log" >&2 || true
  exit 1
fi
python3 "$root/scripts/verify.py" --env "$root/stash-test-server.env"
echo "ready: http://127.0.0.1:$port  (credentials in stash-test-server.env)"
