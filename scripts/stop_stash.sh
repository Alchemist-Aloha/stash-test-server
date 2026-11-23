#!/usr/bin/env bash
# Usage: stop_stash.sh <data-dir>
set -euo pipefail
pid_file="$1/stash.pid"
if [[ -f "$pid_file" ]]; then
  kill "$(cat "$pid_file")" 2>/dev/null || true
  rm -f "$pid_file"
  echo "stash stopped"
fi
