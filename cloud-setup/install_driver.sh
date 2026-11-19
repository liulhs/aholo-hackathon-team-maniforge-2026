#!/usr/bin/env bash
# On a plain Ubuntu 22.04 GPU instance: install the NVIDIA 580-branch driver that Isaac Sim 5.1 needs.
# Why: Isaac Sim 5.1 segfaults in librtx.scenedb on the 590/595 branch (AWS DLAMI ships 595 and its
# boot-time kmod loader re-installs it), and 580.65.06 does not compile on Ubuntu's 6.8 aws kernels.
# 580.196.07 (newest 580 build, 2026-10) compiled against 6.8.0-1069-aws on 2026-11-13.
# Usage: bash ~/cogway/install_driver.sh   (reboots at the end; re-run afterwards to verify)
set -euo pipefail
VERSION=580.196.07
RUN="$HOME/drv/NVIDIA-Linux-x86_64-$VERSION.run"

if nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | grep -q "^$VERSION"; then
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
  ls /etc/vulkan/icd.d/nvidia_icd.json /usr/share/vulkan/icd.d/nvidia_icd.json 2>/dev/null || true
  echo "driver $VERSION is active"
  exit 0
fi

sudo apt-get update -q
# libgl1/libglu1/X11 runtime libs: Isaac Sim's MDL (libneuray) and MaterialX plugins need them even
# headless; without them RTX shaders fail to load and PhysX then hits CUDA illegal-address errors.
sudo apt-get install -y -q build-essential dkms pkg-config "linux-headers-$(uname -r)" \
  libglvnd-dev libvulkan1 vulkan-tools tmux \
  libgl1 libglu1-mesa libegl1 libxt6 libxrandr2 libxinerama1 libxcursor1 libxi6 libsm6 libice6
mkdir -p "$HOME/drv"
[ -f "$RUN" ] || curl -fsSL -o "$RUN" "https://download.nvidia.com/XFree86/Linux-x86_64/$VERSION/NVIDIA-Linux-x86_64-$VERSION.run"
sudo sh "$RUN" --silent --dkms --kernel-module-type=open || {
  echo "full install failed; retrying without nvidia-drm (not needed for headless Vulkan rendering)" >&2
  sudo sh "$RUN" --silent --dkms --kernel-module-type=open --no-drm
}
echo "installed $VERSION; rebooting so the module loads cleanly"
sudo reboot
