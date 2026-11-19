#!/usr/bin/env bash
# On the GPU instance: install Isaac Sim 5.1 + IsaacLab 2.3.0 + LeIsaac into conda env "leisaac".
# Idempotent: each stage writes a marker in ~/cogway/.done/ and is skipped on re-run.
# Usage: bash ~/cogway/setup_instance.sh [check|install|all]   (default: all)
set -euo pipefail
ROOT="$HOME/cogway"
L="$ROOT/leisaac"
DONE="$ROOT/.done"
LOG="$ROOT/setup.log"
ENV=leisaac
CONDA_DIR="$HOME/miniconda3"
# SITE=cn (CompShare, mainland mirrors) or SITE=global (AWS Seoul etc., official sources).
SITE="${SITE:-cn}"
if [ "$SITE" = global ]; then
  PIP_MIRROR="https://pypi.org/simple"
  CONDA_INSTALLER="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
  CONDA_CHANNEL="conda-forge"
else
  PIP_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
  CONDA_INSTALLER="https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/Miniconda3-latest-Linux-x86_64.sh"
  CONDA_CHANNEL="https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge"
fi
NVIDIA_INDEX="https://pypi.nvidia.com"
TORCH_INDEX="https://download.pytorch.org/whl/cu128"
TORCH_FALLBACK_LINKS="https://mirrors.aliyun.com/pytorch-wheels/cu128/"
MIN_DRIVER_MAJOR=580
mkdir -p "$DONE" "$ROOT/out"
exec > >(tee -a "$LOG") 2>&1

stage() { [ -f "$DONE/$1" ] && { echo "[skip] $1"; return 1; }; echo "=== [$(date +%T)] $1"; return 0; }
mark() { touch "$DONE/$1"; }

check() {
  echo "=== instance check (SITE=$SITE)"
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader || { echo "nvidia-smi failed: no GPU driver" >&2; exit 1; }
  local major; major=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 | cut -d. -f1)
  [ "$major" -ge "$MIN_DRIVER_MAJOR" ] || echo "WARN: driver $major < $MIN_DRIVER_MAJOR; Isaac Sim 5.1 may refuse to start"
  echo "os: $(. /etc/os-release && echo "$PRETTY_NAME") | cpu: $(nproc) | ram: $(free -g | awk '/Mem/{print $2}') GiB"
  df -h "$HOME" | tail -1
  echo "--- preinstalled Isaac Sim (from the image), for reference only:"
  ls -d /isaac-sim* "$HOME"/isaacsim* "$HOME"/.local/share/ov/pkg/isaac* 2>/dev/null || echo "none found in common paths"
  docker images 2>/dev/null | grep -i isaac || true
  # Read version metadata only: importing isaacsim triggers the interactive EULA prompt.
  python3 -c "import importlib.metadata as m; print('isaacsim', m.version('isaacsim'))" 2>/dev/null || true
  echo "--- outbound reachability (HTTP code / seconds)"
  for url in "$PIP_MIRROR/pip/" "$NVIDIA_INDEX/isaacsim/" "$TORCH_INDEX/torch/" https://github.com https://huggingface.co; do
    printf '%-55s %s\n' "$url" "$(curl -s -o /dev/null -m 15 -w '%{http_code} %{time_total}' "$url" || echo fail)"
  done
}

install_conda() {
  stage conda || return 0
  if [ ! -x "$CONDA_DIR/bin/conda" ]; then
    curl -fsSL -o /tmp/miniconda.sh "$CONDA_INSTALLER"
    bash /tmp/miniconda.sh -b -p "$CONDA_DIR"
  fi
  "$CONDA_DIR/bin/conda" create -y -n "$ENV" python=3.11 -c "$CONDA_CHANNEL" --override-channels
  mark conda
}

activate() { source "$CONDA_DIR/bin/activate" "$ENV"; export PIP_INDEX_URL="$PIP_MIRROR" PIP_DEFAULT_TIMEOUT=120; }

install_torch() {
  stage torch || return 0
  pip install -U pip
  pip install torch==2.7.0 torchvision==0.22.0 --index-url "$TORCH_INDEX" \
    || pip install torch==2.7.0 torchvision==0.22.0 -f "$TORCH_FALLBACK_LINKS"
  python -c "import torch; assert torch.cuda.is_available(); print('torch', torch.__version__, torch.cuda.get_device_name(0))"
  mark torch
}

install_isaacsim() {
  stage isaacsim || return 0
  pip install "isaacsim[all,extscache]==5.1.0" --extra-index-url "$NVIDIA_INDEX"
  mark isaacsim
}

install_isaaclab() {
  stage isaaclab || return 0
  command -v cmake >/dev/null || sudo apt-get install -y cmake build-essential
  # flatdict==4.0.1 ships only an sdist whose setup.py imports pkg_resources, which setuptools>=81 removed;
  # pip's isolated build pulls the newest setuptools, so build it once against an older setuptools.
  pip install "setuptools<81"
  pip install --no-build-isolation "flatdict==4.0.1"
  (cd "$L/dependencies/IsaacLab" && OMNI_KIT_ACCEPT_EULA=YES ./isaaclab.sh --install none)
  # isaaclab.sh can exit 0 after a failed sub-install, so verify the packages explicitly.
  # (Importing isaaclab_tasks needs the Kit app running for `omni`, so check pip metadata instead.)
  pip show isaaclab isaaclab_tasks isaaclab_assets >/dev/null && echo "isaaclab ok"
  mark isaaclab
}

install_leisaac() {
  stage leisaac || return 0
  pip install -e "$L/source/leisaac"
  pip install "rsl-rl-lib==3.0.1" pyzmq  # light training + remote leader arm; both from PyPI, no GitHub
  grep -q LEISAAC_ASSETS_ROOT "$HOME/.bashrc" || {
    echo "export LEISAAC_ASSETS_ROOT=$L/assets" >> "$HOME/.bashrc"
    echo "export OMNI_KIT_ACCEPT_EULA=YES" >> "$HOME/.bashrc"
  }
  mark leisaac
}

smoke() {
  export LEISAAC_ASSETS_ROOT="$L/assets" OMNI_KIT_ACCEPT_EULA=YES
  cd "$L"
  python scripts/environments/list_envs.py --headless 2>/dev/null | grep -i takeout || echo "WARN: takeout task not listed"
  for task in LeIsaac-SO101-LiftCube-v0 LeIsaac-SO101-LiftTakeoutBox-v0 LeIsaac-SO101-LiftTakeoutBox-Real-v0; do
    obj=takeout_box; [ "$task" = LeIsaac-SO101-LiftCube-v0 ] && obj=cube
    rm -f "$ROOT/out/${task}_result.json"
    python "$ROOT/tools/smoke_test.py" --task "$task" --object "$obj" --headless --enable_cameras || true
    # Kit may swallow exceptions and exit 0: trust only the result file written at the end of the test.
    if grep -q '"settled": true' "$ROOT/out/${task}_result.json" 2>/dev/null; then
      echo "PASS $task"
    else
      echo "FAIL $task (see $LOG)"
    fi
  done
}

MODE="${1:-all}"
case "$MODE" in
  check) check ;;
  install) check; install_conda; activate; install_torch; install_isaacsim; install_isaaclab; install_leisaac ;;
  all) check; install_conda; activate; install_torch; install_isaacsim; install_isaaclab; install_leisaac; smoke ;;
  smoke) activate; smoke ;;
  *) echo "usage: $0 [check|install|all|smoke]" >&2; exit 2 ;;
esac
echo "=== [$(date +%T)] done ($MODE). log: $LOG"
