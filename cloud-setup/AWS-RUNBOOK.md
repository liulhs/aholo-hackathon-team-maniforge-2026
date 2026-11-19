# AWS 首尔：接手与重新开机手册

写于 2026-11-14，对应 2026-11-13 实际跑通的环境。`README.md` 是开机前为 CompShare 写的计划；**实际在用的是这台 AWS 机器，以本文为准。** 每个坑的现象、原因和处理见 [../gotchas/README.md](../gotchas/README.md)，本文只写“现在是什么状态、下一步怎么继续、还卡在哪里”。

## 现在的状态（2026-11-14 核对）

| 项 | 值 |
| --- | --- |
| 实例 | `<instance-id>`，g6.2xlarge（L4 24 GB、8 vCPU、规格 32 GiB / 系统显示约 30 GiB），`ap-northeast-2a` |
| 状态 | **stopped**（2026-11-13 23:16 北京时间停机）。停机只收 200 GB gp3 硬盘费，约 $0.6/天；开机后 $1.20/时 |
| 系统 | Canonical 纯净 Ubuntu 22.04，`ami-079679697f41501ee`；硬盘 `vol-009ca8c43ecba448c` |
| 登录 | 密钥对 `cogway-mac`（Mac 上的 `~/.ssh/id_rsa`），用户 `ubuntu` |
| 安全组 | `<security-group-id>`，只放行 TCP 22、TCP 49100、UDP 47998，来源只有两个 IP：`<home-ip>/32`（用户家里的真实出口，中国移动）和 `<vpn-ip>/32`（用户 VPN 出口） |
| 公网 IP | 停机时已释放，**开机后会换新 IP** |
| 配额 | 首尔 G 系列按需 8 vCPU（刚好够这一台）。同时开两台会报 `VcpuLimitExceeded` |
| 已装好 | 驱动 580.196.07（DKMS，开源内核模块）、Miniforge 环境 `leisaac`（Python 3.11）、PyTorch 2.7.0 cu128、Isaac Sim 5.1.0（pip）、IsaacLab @`3c6e67b`（0.47.2）、LeIsaac @`24d3bcd`、rsl-rl-lib 3.0.1、pyzmq。标记文件在 `~/cogway/.done/`，重跑安装会跳过 |
| 许可 | 用户已在 2026-11-13 本人同意 NVIDIA Omniverse 许可协议，所以脚本里设了 `OMNI_KIT_ACCEPT_EULA=YES`。换新机器或新账号要重新征得用户同意 |

## 给接手 agent 的规矩

- **花钱的操作先问用户：** 开机、新建、删除实例都要用户点头。用完提醒停机。
- **安全组不对外开放：** 排查时临时放开到 `0.0.0.0/0`，查完立刻撤回，并告诉用户。
- **本机 `aws` 默认区域是 `us-east-2`：** 每条命令都带 `--region ap-northeast-2`，或先 `export AWS_REGION=ap-northeast-2`，否则查不到这台实例。
- **别用 `pkill -f <词>`：** 它会匹配到执行它的那条 SSH 命令，把自己的连接杀掉。用 `killall python` 或 `pkill -f "[t]eleop"`，同一条命令里别再出现这个词。
- **长任务放 tmux：** 安装、遥操作都在 `tmux new -d -s <名字> "..."` 里跑，避免 SSH 断开时中断。
- **结果写回：** 每次在机器上跑出结果，按 `../AGENTS.md` 写回 `../README.md` 的进度记录。

## 重新开机（按顺序）

```bash
export AWS_REGION=ap-northeast-2
aws ec2 start-instances --instance-ids <instance-id>
aws ec2 wait instance-running --instance-ids <instance-id>
aws ec2 describe-instances --instance-ids <instance-id> --query 'Reservations[0].Instances[0].PublicIpAddress' --output text
```

拿到新 IP 后：

1. **让用户改 VPN：** 把直连规则改成 `IP-CIDR <新IP>/32 DIRECT`，放在规则列表最上面。用户的 VPN 只转发 TCP，推流画面走 UDP 47998，不加这条就黑屏。
2. **核对用户当前出口 IP：** 让用户在浏览器打开 `myip.ipip.net`。中国移动家宽的 IP 可能会变，如果不再是 `<home-ip>`，把安全组里三条 `*-home` 规则换成新 IP。
3. **同步最新文件：** 本地的键盘补丁等改动可能还没上机，开机后先同步一次（会先跑 `stage_bundle.sh` 打补丁，可重复执行）：
   ```bash
   ./sync_to_instance.sh ubuntu@<新IP>
   ```
4. **自检：** `ssh ubuntu@<新IP> 'SITE=global bash ~/cogway/setup_instance.sh check'`，确认驱动仍是 580.196.07。**`SITE` 默认是 `cn`（清华源），在 AWS 上必须写 `SITE=global`。**
5. **遥操作：**
   ```bash
   ssh ubuntu@<新IP> 'tmux new -d -s teleop "bash ~/cogway/run_teleop.sh > ~/cogway/teleop.log 2>&1"'
   ```
   第一次启动要编译着色器，等 1–3 分钟，看 `~/cogway/teleop.log` 不再刷屏后，在 Mac 的 **Isaac Sim WebRTC Streaming Client 1.1.5** 里填新 IP。录数据时在 `run_teleop.sh` 后面加 `--record`，数据存到 `~/cogway/datasets/<任务名>.hdf5`。
6. **用完停机：**
   ```bash
   aws ec2 stop-instances --instance-ids <instance-id>
   aws ec2 wait instance-stopped --instance-ids <instance-id>
   ```

## 如果要从零重建

机器坏了或要换区域时，照这个顺序，约 30–40 分钟到冒烟测试：

1. 用纯净 Ubuntu 22.04，**不要用 AWS 深度学习镜像**：它自带 595 驱动，Isaac Sim 5.1 会段错误，而且开机服务会把驱动装回 595。也不要用 Marketplace 上 NVIDIA 的 Isaac Sim 镜像：2026-09-29 发布，看不出版本，多半是 6.x，而 LeIsaac 只支持 5.1；订阅它还要用户同意条款。
2. 硬盘 200 GB gp3；安全组只放行上面三个端口和用户的 IP。
3. `./sync_to_instance.sh ubuntu@<IP>`
4. `ssh ubuntu@<IP> 'bash ~/cogway/install_driver.sh'`：装依赖库和 580.196.07 驱动，会自动重启；重启后再跑一次同一条命令，确认驱动。
5. 征得用户同意 NVIDIA Omniverse 许可协议后：
   ```bash
   ssh ubuntu@<IP> 'tmux new -d -s setup "SITE=global bash ~/cogway/setup_instance.sh all"'
   ```
6. 看 `~/cogway/setup.log` 末尾：两个外卖盒任务应是 PASS。`LiftCube` 显示 FAIL 是判定脚本的已知问题（见下文），看它的 `bottom_z` 约 0.056 即正常。

## 还卡着的坎

都还没解决，按对黑客松的影响排序：

| 坎 | 现状 | 下一步 |
| --- | --- | --- |
| 还没录任何示范数据 | 只练过键盘遥操作，没跑过 `--record` | 用主臂录 30–50 条 |
| 键盘录的数据不能直接用于 LeIsaac 的策略推理 | 键盘动作是 8 维的末端增量，策略推理要的是主臂录的关节角 | 用实体 SO-101 主臂遥操作（LeIsaac 的 `so101leader` 或远程 ZMQ 模式）。主臂接在用户的 Mac 上，要经 SSH 反向隧道把端口 5556 转到服务器，**这条链路还没试过** |
| 键盘按键卡住的补丁没在线上复测 | `patches/so101_keyboard_held_keys.patch` 只在本地用桩代码测过 | 开机同步后按 B，单按 A、D 看能否左右转、松手即停 |
| 外卖盒的质量和摩擦是假设值 | 质量 0.02 kg，摩擦静 0.6 / 动 0.5 | 称实物重量，用 `build_takeout_box_usd.py --mass-kg` 重新生成；抓取打滑再调摩擦 |
| 冒烟测试误判 LiftCube | 判定按“原点在物体底部”写，方块原点在中心 | 改 `smoke_test.py`：按包围盒底部算，而不是按原点 |
| 24 GB 的 L4 可能不够微调 GR00T | 社区经验：N1.5 微调约需 25 GB 以上，N1.7 建议 40 GB 以上（未实测） | 先训 ACT（约 8000 万参数，24 GB 足够）；要 GR00T 就换 g6e（L40S 48 GB），需要再提配额 |
| Isaac Sim 5.1 已不是最新版 | 官方文档标“不再支持”；IsaacLab 3.x 不支持 5.1 | 黑客松期间锁定 5.1 + IsaacLab 2.3.0 + LeIsaac 0.4.0，不要升级 |
| 主臂和仿真的关节零点可能对不上 | LeIsaac 把电机读数线性映射到仿真关节角，真机没校准时会偏 | 先用 LeRobot 校准实体臂，再对比同一姿态下真机和仿真的关节角 |
