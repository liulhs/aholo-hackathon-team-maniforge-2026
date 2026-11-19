#!/usr/bin/env bash
# Download the MuJoCo Menagerie SO-101 model into sim/models/so101 (not committed; ~18 MB of STL).
# Pinned to one Menagerie commit so joint conventions don't shift under the teleop mapping.
set -euo pipefail

MENAGERIE_REPO="https://github.com/google-deepmind/mujoco_menagerie"
MENAGERIE_COMMIT="${MENAGERIE_COMMIT:-370c43965323c0944b433b202aac5058b5f907a9}"
SIM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SIM_DIR/models/so101"
WORK="$SIM_DIR/models/.menagerie"

derive_nocam() {
  python3 "$SIM_DIR/make_nocam_model.py"
  python3 "$SIM_DIR/prep_object.py" --all  # Lux3D objects -> sim/models/objects (needs the .venv)
}

if [[ -f "$TARGET/so101.xml" ]]; then
  echo "Already present: $TARGET (delete it to re-download)"
  derive_nocam
  exit 0
fi

rm -rf "$WORK"
git clone --quiet --filter=blob:none --sparse "$MENAGERIE_REPO" "$WORK"
git -C "$WORK" checkout --quiet "$MENAGERIE_COMMIT"
git -C "$WORK" sparse-checkout set robotstudio_so101
mkdir -p "$(dirname "$TARGET")"
cp -R "$WORK/robotstudio_so101" "$TARGET"
echo "Menagerie commit: $(git -C "$WORK" rev-parse HEAD)" | tee "$TARGET/MENAGERIE_COMMIT.txt"
rm -rf "$WORK"
echo "SO-101 model in $TARGET"
derive_nocam
