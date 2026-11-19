#!/usr/bin/env bash
# On the GPU instance: keyboard teleop of the takeout-box task, viewed through Isaac Sim WebRTC livestream.
# Usage: bash ~/cogway/run_teleop.sh [task] [--record]
#   task defaults to LeIsaac-SO101-LiftTakeoutBox-v0; --record saves ~/cogway/datasets/<task>.hdf5
# Connect from the Mac with the Isaac Sim WebRTC Streaming Client to this instance's public IP.
# Keys after the window streams: B = start teleop, W/S A/D Q/E = move, J/L K/I = rotate, U/O = gripper,
# R = reset (see LeIsaac docs/resources/available_devices.md).
set -euo pipefail
TASK="${1:-LeIsaac-SO101-LiftTakeoutBox-v0}"
shift || true
source "$HOME/miniconda3/bin/activate" leisaac
export LEISAAC_ASSETS_ROOT="$HOME/cogway/leisaac/assets" OMNI_KIT_ACCEPT_EULA=YES
cd "$HOME/cogway/leisaac"
EXTRA=()
if [ "${1:-}" = "--record" ]; then
  mkdir -p "$HOME/cogway/datasets"
  EXTRA=(--record --dataset_file="$HOME/cogway/datasets/${TASK}.hdf5")
fi
# Remote WebRTC needs the instance's public IP and open ports UDP 47998 + TCP 49100 (Isaac Sim 5.1 docs).
PUBLIC_IP="${PUBLIC_IP:-$(curl -s -m 10 ifconfig.me || true)}"
[ -n "$PUBLIC_IP" ] || { echo "set PUBLIC_IP=<instance public IP from the CompShare console>" >&2; exit 1; }
echo "streaming on $PUBLIC_IP:49100 — open it in the Isaac Sim WebRTC Streaming Client 1.1.5"
# IsaacLab 2.3 / Isaac Sim 5.1: --livestream 1 = WebRTC over public network. AppLauncher then enables
# omni.services.livestream.nvcf with publicEndpointAddress=$PUBLIC_IP and port 49100. Enabling
# omni.kit.livestream.webrtc by hand (as in the Brev doc) lets the client connect but never streams video.
export PUBLIC_IP
python scripts/environments/teleoperation/teleop_se3_agent.py \
  --task="$TASK" --teleop_device=keyboard --num_envs=1 --device=cuda --enable_cameras \
  --livestream 1 "${EXTRA[@]}"
