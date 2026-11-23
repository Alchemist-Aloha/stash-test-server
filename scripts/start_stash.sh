#!/usr/bin/env bash
# Start ./bin/stash in the background with an isolated HOME so it never reads
# a developer's real ~/.stash. The server comes up in first-run SETUP state;
# seed.py completes setup.
# Usage: start_stash.sh <data-dir> [port]
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
data_dir="$(mkdir -p "$1" && cd "$1" && pwd)"
port="${2:-9999}"

mkdir -p "$data_dir/home"
cd "$data_dir"
HOME="$data_dir/home" \
STASH_HOST=127.0.0.1 \
STASH_PORT="$port" \
STASH_NOBROWSER=true \
  nohup "$root/bin/stash" --host 127.0.0.1 --port "$port" --nobrowser \
  > "$data_dir/stash.log" 2>&1 &
echo $! > "$data_dir/stash.pid"
echo "stash started (pid $(cat "$data_dir/stash.pid"), port $port, log $data_dir/stash.log)"
