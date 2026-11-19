#!/usr/bin/env bash
# Local (Mac): push bundle/ to the instance as ~/cogway. Usage: ./sync_to_instance.sh ubuntu@<public-ip> [ssh-port]
set -euo pipefail
TARGET="${1:?usage: sync_to_instance.sh user@host [port]}"
PORT="${2:-22}"
HERE="$(cd "$(dirname "$0")" && pwd)"
"$HERE/stage_bundle.sh"
# macOS ships openrsync (2.6.9-compatible): no --info=progress2, use --progress instead.
rsync -az --partial --progress -e "ssh -p $PORT -o ServerAliveInterval=30" \
  "$HERE/bundle/" "$TARGET:~/cogway/"
echo "synced to $TARGET:~/cogway"
