# 抓取训练计划：人示范 + 小模型（2026-11-16 定）

## 为什么做这个

竞品调研（未公开）里 108 个公开作品，没有一个是「人示范 → 训练模型 → 模型自己抓」。最接近的 EmbodiedWorld 也用 SO-101 + MuJoCo 抓取，但只是人手动逐关节操控，没有训练模型。我们要讲的故事：

> 人用真实 SO-101 示范几十次 → 小模型（ACT）学会抓 → 模型自己抓，成功率 X% → 抓失败时人接管纠正 → 纠正数据让下一版更好。

报告里必须如实写：**模型在仿真里学会抓取，真机在这里是遥控器**。成功率是多少写多少。

## 硬件现状（详见 [SO101-NEXT-STEPS.md](SO101-NEXT-STEPS.md)）

- 两只机械臂，都按「从臂」组装（末端是夹爪，不是手柄加扳机）。用户核对过其中一只：6 个舵机全是 STS3215 7.4V、减速比 1/147（C046），不是官方从臂的 1/345；第二只是不是一样还没核对。
- 电源：两个附送适配器型号相同，YX-07250，7.2V 5A，圆孔内正外负。
- 驱动板：Waveshare Bus Servo Adapter (A) V1.1，跳线帽在 B（USB）位。
- 1/147 好掰，适合当遥控器；力矩只有 1/345 的约 43%，真机自己抓只能拿很轻的东西。
- **臂 A 已就绪（2026-11-16）：** 舵机 ID 1–6 已设好（出厂全是 ID 1，卖家没设），已按主臂模式校准，校准名 `arm_a`。LeRobot 0.7.0 装在 conda 环境 `lerobot`，端口 `/dev/tty.usbmodem5B910285391`。详见 README 进度记录。
- 还没做：第二只臂的舵机型号核对、设 ID、校准。

## 选定方案：MuJoCo（本机）为主，LeIsaac（AWS）为保底

| | MuJoCo（Mac 本机） | Isaac Sim / LeIsaac（AWS） |
| --- | --- | --- |
| 遥控延迟 | 从臂插 Mac，几乎为零 | 隔着网络和推流，有延迟，影响示范质量 |
| 成本 | 不花钱 | 每小时 $1.20，开机要问用户 |
| 抓取物理 | 已验证（见 [CPU 验证](experiments/2026-11-15-mujoco-cpu-spike/README.md)） | 场景能跑，遥控抓取还没试 |
| 现成工具 | 要自己写衔接代码 | 遥控、只存成功示范、转格式、ACT 推理接口都有（`--teleop_device=so101leader`、`--use_lerobot_recorder`、`--policy_type=lerobot-act`） |
| 和网页 Demo | 同一个仿真，轨迹可在浏览器逐位一致重放 | 两套环境 |

**进度（11/16）：** 从臂 → MuJoCo 已打通，见 [sim/README.md](sim/README.md)。

**保底规则：** 先花 1–2 小时打通「从臂 → MuJoCo 手臂跟着动」。到 11/17 中午还没通，就改走 LeIsaac。

## MuJoCo 路线要写的东西

1. **关节角对应**：从臂读数（LeRobot 校准后）→ Menagerie SO-101 关节角，处理零点偏移和方向。最大风险点。
2. **录制**：每步存仿真相机画面、关节状态、动作，写成 LeRobot 数据格式；只保存成功的示范。
3. **训练**：LeRobot 的 ACT。Mac GPU（MPS）能跑但慢，必要时把数据传到 AWS 训练。
4. **评估**：模型在 MuJoCo 里自己抓 N 次统计成功率，轨迹存下来可回放。
5. 已知坑：macOS 上 MuJoCo 实时窗口要用 `mjpython` 启动。


## 实测记录（2026-11-16）

- **示范数据：** `data/so101_takeout_lift`，43 个成功回合、5328 帧，每秒 20 帧，回合中位长度 5.8 秒。抓取位置铺满了随机区域，仿真跟真臂的关节误差中位 < 1°。录制方法见 [sim/README.md](sim/README.md)。
- **Mac 训练速度（M4 Pro，MPS，lerobot 0.7.0 ACT 默认配置，5200 万参数）：** batch 8 每步 0.178 秒，约 45 样本/秒；batch 32 每步 0.600 秒，约 53 样本/秒，提速不明显。读数据不是瓶颈（data_s 约 0.003 秒）。前 200 步 loss 从 24 降到 3.4，没有报错。
- **时间估算（batch 8）：** 2 万步约 1 小时，3 万步约 1.5 小时，10 万步（LeRobot 默认）约 5 小时。
- **注意：** ACT 默认 `chunk_size=100`，按每秒 20 帧算是 5 秒，几乎等于整个回合的长度。

### 旧场景数据的完整训练（2026-11-17）

- **数据：** 上面的 `data/so101_takeout_lift`（蓝格子地面、黄色机械臂的旧场景，没有存仿真状态）。
- **命令：** `lerobot-train --dataset.repo_id=maniforge/so101_takeout_lift --dataset.root=data/so101_takeout_lift --policy.type=act --policy.device=mps --policy.push_to_hub=false --policy.chunk_size=40 --policy.n_action_steps=40 --batch_size=8 --steps=30000 --save_freq=5000 --log_freq=200 --output_dir=outputs/act_takeout_lift_old`。lerobot 0.7.0 没有 `--wandb.enable` 参数，带上会直接报错退出。
- **结果：** 3 万步用了 78 分钟（每秒 6.5 步），没有报错。loss 从第 200 步的 6.81 降到 0.077；其中 l1_loss 从 0.636 降到 0.072（归一化后的动作误差），最后 3000 步仍在缓慢下降。
- **产物：** `outputs/act_takeout_lift_old/checkpoints/`，每 5000 步一个检查点，共 3.5 GB，不进 git。日志在 `outputs/act_takeout_lift_old.log`。
- **没做的：** 没有评估成功率。评估要在旧场景里让模型自己抓，而 `sim/lift_scene.py`（当时叫 `takeout_scene.py`）现在生成的是书桌场景，旧场景要另外搭回来。

### 不看图像的通用模型（2026-11-19 凌晨）

- **数据：** 新的小桌场景，五个物体各 40 个真臂示范，合成一个只有关节角、物体状态和动作的数据集（`sim/build_state_dataset.py`）。
- **结果：** ACT 缩小到 740 万参数，30000 步，物体状态归一化，推理时做时间平均：500 次随机尝试抬起 74%。每个物体只用 20 个示范时 38%；不归一化物体状态时 65%。详见 [sim/README.md](sim/README.md)。
- **结论：** 一个模型能同时抓五种物体；示范数量是目前最主要的瓶颈；失败几乎都是在桌上碰倒物体。

## 时间估计（截止 11/19 19:00 北京时间 = 11/19 06:00 美东）

| 步骤 | 时间 |
| --- | --- |
| 舵机 ID / 校准 | 1–2 小时（用户动手） |
| 打通遥控 | 1–2 小时 |
| 录 40 次示范 | 1–1.5 小时 |
| 训练 ACT | 估计 2–3 小时（未实测） |
| 评估、录视频素材 | 1–2 小时 |
