# CompShare 上线手册：SO-101 抓 Lux3D 外卖盒

> **本文是开机前为 CompShare 写的计划，已过时。** 2026-11-13 实际是在 AWS 首尔跑通的（纯净 Ubuntu 22.04 + `install_driver.sh` 装 580.196.07 驱动 + `SITE=global`）。机器现状、重新开机和从零重建的步骤看 [AWS-RUNBOOK.md](AWS-RUNBOOK.md)；所有踩过的坑见 [../gotchas/README.md](../gotchas/README.md)。下文的文件说明和外卖盒物理参数仍然有效。

准备于 2026-11-13。目标：开机后只跑脚本，少花计费时间。机器配置：CompShare 华北二A，RTX 4090 24G，16C 94GB，镜像 Isaac Sim Webrtc（Ubuntu 22.04 虚拟机），按量 ¥2.35/时。

## 已在本地准备好的东西

| 文件 | 作用 |
| --- | --- |
| `bundle/` | 开机后整包同步到实例的 `~/cogway/`（195 MB）。含 LeIsaac @`24d3bcd`、IsaacLab @`3c6e67b`（LeIsaac 锁定版本，对应 Isaac Sim 5.1）、SO-101 机器人、桌子场景、两个外卖盒场景、我们的任务和脚本。实例上不用访问 GitHub 和 Hugging Face |
| `build_takeout_box_usd.py` | 把 Lux3D 产物转成带物理属性的 USD：外观用 `textured.glb`（贴图转成 UsdPreviewSurface），碰撞用 `raw_mesh.glb` 的凸包（784 个顶点），glTF 的 Y 轴向上转成 Z 轴向上，盒底放在原点 |
| `assets/scenes/table_with_takeout_box*/` | 生成好的场景：LeIsaac 的桌子 + 外卖盒，放在原来方块的位置 |
| `leisaac_task/lift_takeout_box/` | 两个任务：`LeIsaac-SO101-LiftTakeoutBox-v0`（小号盒，默认）、`LeIsaac-SO101-LiftTakeoutBox-Real-v0`（Lux3D 尺寸） |
| `setup_instance.sh` | 实例上一键安装：Miniconda（清华镜像）→ PyTorch 2.7.0 cu128 → `isaacsim[all,extscache]==5.1.0` → IsaacLab（`--install none`，跳过要走 GitHub 的 rl-games）→ LeIsaac + rsl-rl。每一步有完成标记，中断后重跑会跳过已完成的步骤 |
| `smoke_test.py` | 无界面检查：任务能加载、盒子在桌面上停稳，存一张前置相机截图 |
| `run_teleop.sh` | 键盘遥操作 + WebRTC 推流，`--record` 时录 HDF5 数据 |
| `stage_bundle.sh` / `sync_to_instance.sh` | 本地刷新 bundle，并用 rsync 推到实例 |

### 外卖盒的物理参数（全部可改）

| 参数 | 当前值 | 来源 |
| --- | --- | --- |
| 尺寸 | 小号：0.051 × 0.055 × 0.055 m；真实尺寸版：0.111 × 0.120 × 0.120 m | 小号按 SO-101 夹爪缩放；真实尺寸版是 Lux3D 的 AI 预测值 |
| 质量 | 0.02 kg | **假设值**，称重后用 `--mass-kg` 重新生成 |
| 摩擦 | 静 0.6 / 动 0.5 | **假设值**，抓取测试后调整 |
| 碰撞 | 凸包 | 盒子体积约为凸包的 82%，凸包够用 |

**为什么默认用小号盒：** 从 SO-101 的碰撞网格算出，夹爪有效开口约 6–7 cm（45° 时指尖间距 67 mm），12 cm 的盒子夹不住。真实尺寸版保留下来，用于演示“生成尺寸不对时会怎样”。

## 开机前（你来做）

1. **充值：** 账户余额只有 ¥5（约 2 小时）。按量是后付费，欠费 12 小时后实例会被回收，数据清空。
2. **下载推流客户端：** 从 [Isaac Sim 5.1 下载页](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/download.html) 下载 **Isaac Sim WebRTC Streaming Client 1.1.5，macOS arm64**。
3. **确认盒子尺寸方案：** 默认用小号盒，也可以换成更小的真实物体重新生成。

## 开机后（按顺序）

预计计费时间：安装 40–90 分钟，主要花在下载 Isaac Sim 的 pip 包上；冒烟测试 10 分钟。

1. **创建实例：** 用上面的配置。记下公网 IP、SSH 端口、用户名和登录密码。
2. **开放防火墙：** 在 CompShare 控制台的“外网防火墙”放行 **TCP 22、TCP 49100、UDP 47998**，并绑定到实例。
3. **配 SSH 免密：**
   ```bash
   ssh-copy-id -p <端口> ubuntu@<公网IP>
   ```
4. **同步 bundle：**
   ```bash
   ./sync_to_instance.sh ubuntu@<公网IP> <端口>
   ```
5. **自检：**
   ```bash
   ssh ubuntu@<公网IP> 'bash ~/cogway/setup_instance.sh check'
   ```
   看驱动版本（要求 ≥580）、显存、硬盘，以及到清华源、NVIDIA、PyTorch 的网络连通情况。
6. **安装和冒烟测试：** 在 tmux 里运行，避免断线中断：
   ```bash
   ssh ubuntu@<公网IP> 'tmux new -d -s setup "bash ~/cogway/setup_instance.sh all"'
   ```
   结束后看 `~/cogway/setup.log` 末尾，应依次出现：
   - `PASS LeIsaac-SO101-LiftCube-v0`（官方任务，用来确认环境本身没问题）
   - `PASS LeIsaac-SO101-LiftTakeoutBox-v0`
   - `PASS LeIsaac-SO101-LiftTakeoutBox-Real-v0`

   截图在 `~/cogway/out/`，取回本地：
   ```bash
   scp ubuntu@<公网IP>:~/cogway/out/*.png .
   ```
7. **遥操作：**
   ```bash
   ssh ubuntu@<公网IP> 'bash ~/cogway/run_teleop.sh'
   ```
   在 Mac 的 Streaming Client 里输入公网 IP。按 `B` 开始，`W/S/A/D/Q/E` 移动，`J/L/K/I` 转动，`U/O` 开合夹爪，`R` 重置。录数据时加 `--record`。
8. **用完关机：** 关机后 GPU 不收费，但连续关机 7 天实例会被回收。

## 失败时先查这里

| 现象 | 处理 |
| --- | --- |
| PyTorch 从 download.pytorch.org 下载很慢 | 脚本会自动改用阿里云镜像（这个回退地址未在实例上验证过） |
| `pypi.nvidia.com` 下载慢或超时 | 重跑 `setup_instance.sh install`，已完成的步骤会跳过 |
| LiftCube 通过、外卖盒失败 | 问题在我们的资产：看日志里的 `bottom_z`；在本地改 `build_takeout_box_usd.py` 后，重跑 `stage_bundle.sh` 和 `sync_to_instance.sh` |
| 推流黑屏 | 确认 UDP 47998 已放行；第一次启动要编译着色器，可能要几分钟 |
| 驱动低于 580 | 镜像驱动太旧，需要换镜像或升级驱动 |

## 重新生成外卖盒资产

```bash
python3 -m venv .venv && .venv/bin/pip install usd-core numpy pillow scipy
.venv/bin/python build_takeout_box_usd.py --variant small --cube-scene bundle/leisaac/assets/scenes/table_with_cube/scene.usd --mass-kg 0.02
./stage_bundle.sh
```

## 验证情况

- 2026-11-13 已在 AWS 首尔的 Isaac Sim 5.1 里实际跑通安装、冒烟测试和 WebRTC 遥操作，见 [AWS-RUNBOOK.md](AWS-RUNBOOK.md)。
- CompShare 这条路线（`SITE=cn`、清华源、阿里云 PyTorch 回退）**从未在实例上跑过**。
