#!/usr/bin/env bash
# Local (Mac): refresh bundle/ with our task, scenes and scripts before syncing to the GPU instance.
# bundle/leisaac already holds LeIsaac @24d3bcd + IsaacLab @3c6e67b + so101_follower.usd + table_with_cube.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
B="$HERE/bundle"
L="$B/leisaac"

[ -d "$L/dependencies/IsaacLab/source" ] || { echo "bundle/leisaac missing; re-run the clone step in README" >&2; exit 1; }
[ -f "$L/assets/robots/so101_follower.usd" ] || { echo "so101_follower.usd missing in bundle" >&2; exit 1; }

# Local fixes to LeIsaac, applied once (idempotent): see patches/*.patch headers.
for p in "$HERE"/patches/*.patch; do
  [ -f "$p" ] || continue
  if git -C "$L" apply --reverse --check "$p" 2>/dev/null; then
    echo "patch already applied: $(basename "$p")"
  else
    git -C "$L" apply "$p" && echo "applied patch: $(basename "$p")"
  fi
done

rm -rf "$L/source/leisaac/leisaac/tasks/lift_takeout_box"
cp -R "$HERE/leisaac_task/lift_takeout_box" "$L/source/leisaac/leisaac/tasks/"
for scene in table_with_takeout_box table_with_takeout_box_small; do
  [ -f "$HERE/assets/scenes/$scene/scene.usd" ] || { echo "run build_takeout_box_usd.py first ($scene)" >&2; exit 1; }
  rm -rf "$L/assets/scenes/$scene"
  cp -R "$HERE/assets/scenes/$scene" "$L/assets/scenes/"
done
rm -f "$B/smoke_test.py"
mkdir -p "$B/tools"
cp "$HERE/smoke_test.py" "$B/tools/"
cp "$HERE/setup_instance.sh" "$HERE/run_teleop.sh" "$HERE/install_driver.sh" "$B/"
chmod +x "$B/setup_instance.sh" "$B/run_teleop.sh" "$B/install_driver.sh"
du -sh "$B"
echo "bundle ready: $B"
