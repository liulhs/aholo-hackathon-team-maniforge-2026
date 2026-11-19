# SO-101 下一步：预训练模型、真机上电、固定、GPT 物理属性

调研日期 **2026-11-15**，距截止（11-19 19:00）还有 4 天。

思路：Lux3D 生成物体 → GPT 补物理属性 → SO-101 抓起来。这份文档回答三个问题：
- 有没有现成能抓任意物体的模型；
- 真机怎么上电、怎么固定在桌上；
- GPT 补物理属性怎么做才站得住。

> 先说一个可能的口误：你说的「Luma 3D」，我按群核的 **Lux3D** 理解，比赛规定必须用它。Luma AI 是另一家公司。

## 结论先行

1. **没有能直接抓任意物体的 SO-101 开源模型。** 公开的 SO-101 模型都是在单个任务上用 50–100 条示范微调出来的，比如捡橘子、收笔、夹方块。
2. **4 天内要做到「抓任意 Lux3D 物体」，最快的路不靠模型。** LeIsaac 自带一个脚本化抓取程序（`pick_orange.py` 状态机），它从仿真里直接读物体的真实位置，再用逆运动学（IK，把手要去的位置换算成各关节角度）去抓。改成我们的物体，大约 1 天能跑通。
3. **真机今天只用 Mac，花半天以内。** 步骤是：先固定，再核对电压，然后设电机 ID、校准、小幅动一下。真机只做加分演示，不承担「自主抓取」。
4. **「GPT 补物理属性」不是新点子，卖点在闭环。** PhysGen、EmbodiedGen、PUGS、NeRF2Physics 都做过，质量估计的误差普遍在 2 倍左右。我们的卖点是「GPT 先估 → 真实测量 → v0/v1/v2 三版对比」，正好可以当报告要求的迭代对比。

## 一、预训练模型：有什么，能不能直接用

| 模型 | 现状 | 能否直接抓我们的物体 |
| --- | --- | --- |
| [lerobot/smolvla_base](https://huggingface.co/lerobot/smolvla_base) | 约 5 亿参数的基础模型。模型卡写明「要在你的任务上微调」 | 不能。官方建议约 50 条示范，25 条效果差；在 A100 上 2 万步约 4 小时，L4 估计要 8–12 小时 [文档](https://huggingface.co/docs/lerobot/smolvla) |
| [LightwheelAI/leisaac-pick-orange-v0](https://huggingface.co/LightwheelAI/leisaac-pick-orange-v0) | LeIsaac 官方发布的 GR00T N1.5 权重，用 60 条捡橘子数据训练 | 只会捡橘子 |
| [wsagi/GR00T-N1.6-PickOrange](https://huggingface.co/wsagi/GR00T-N1.6-PickOrange) | 社区微调版，9 个橘子放对 8 个，但不同检查点之间差异很大 | 只会捡橘子。在 24 GB 显卡上训成过，L4 显存够，瓶颈是训练速度 |
| openpi（pi0 / pi0.5） | 官方只有 DROID、ALOHA、LIBERO 机器人的微调权重，没有 SO-101 的 | 不能 |
| NVIDIA GR00T SO-101 教程 | 用 80 条「收笔」数据微调，需要约 25 GB 显存，没有发布权重 | 不能 |
| X-VLA、DM0.5、DreamZero 等 | 都要微调。DreamZero 生成的是想象出来的视频，不是控制策略 | 不能 |

**结论：** 学出来的模型只会做训练时那一个任务，换物体、换相机、换光照都会掉成功率。在评委面前说「预训练模型能抓任意 Lux3D 物体」站不住。

### 推荐路线：脚本化抓取 + 可选学习策略

**第 1 天：让脚本抓起外卖盒（在 AWS L4 上，LeIsaac 环境里）**
1. 先跑官方示例，确认状态机能用：`python scripts/datagen/state_machine/generate.py --task LeIsaac-SO101-PickOrange-v0 --num_envs 1 --device cuda --enable_cameras`。加上我们 WebRTC 推流用的参数。
2. 写 `source/leisaac/leisaac/datagen/state_machine/lift_object.py`：
   - 从 `pick_orange.py` 复制出 `LiftObjectStateMachine`。
   - 用 `env.scene[<物体>].data.root_pos_w` 读位置，抓取高度取包围盒的一半。
   - 阶段是：接近 → 悬停 → 下降 → 合爪 → 抬起 → 停 1 秒。
   - 成功判定：物体比桌面高 5 cm 以上。
3. 在 `generate.py` 的 `TASK_REGISTRY` 里注册 `LeIsaac-SO101-LiftTakeoutBox-v0`。之后调 `_GRIPPER_OFFSET`、下降深度和 IK 参数，直到盒子能抬起来。物体放得离底座近一些，成功率更高。

**第 2 天：泛化到多个 Lux3D 物体**
- 把物体的 USD 路径、缩放、质量、摩擦做成参数，GPT 的结果从这里接进来（见第三部分）。
- 用 5–10 个 Lux3D 物体跑一遍，记录每个物体的成功率，存成 CSV。
- 真实尺寸的盒子（12 cm）会夹不住，这正好是一个可以讲的「失败 → 修正」案例。

**第 3 天（可选）：在脚本数据上训练一个学习策略**
1. 加 `--record --num_demos 50` 录 50 条示范。
2. 用 `scripts/mimic/eef_action_process.py --to_joint` 把动作转成关节角，再转成 LeRobot 格式。
3. 先训 ACT，它最快。
4. 说明：
   - 「键盘或脚本录的末端增量动作能转成关节角」是读代码推断出来的，还没有用我们的数据实测过。
   - LeIsaac 的推理锁定 lerobot 0.3.3/0.4.2，训练和推理必须用同一个 lerobot 版本。

**真机这条线：** 只做开环回放，或者用手机遥操作抓一次，报告里如实写。没有主臂的话，真机录不了可用来训练的数据。

## 二、真机：上电与固定（今天在 Mac 上做）

**「运控」是什么：** 不用另装运控固件。它就是那块总线舵机控制板（Waveshare 或 Feetech）加上 LeRobot 软件。要做的是：给每个舵机设 ID，然后校准。

### 0. 先固定，后上电

**官方实际怎么夹（2026-11-15 核实）**

SO-101 的底座**没有专门的夹具零件，也没有螺丝孔位要求**，就是用普通木工夹，把底座两侧的格栅平板直接压在桌面上。

依据有三处：
- **LeRobot 官方校准视频**的截图：[references/so101-official-clamp.jpg](references/so101-official-clamp.jpg)，原视频是 [calibrate_so101_2.mp4](https://huggingface.co/datasets/huggingface/documentation-images/resolve/main/lerobot/calibrate_so101_2.mp4)。
  - 画面里用的是**蓝黑色的扳机式快速夹**（单手按扳机就能收紧的那种）。
  - 夹子的长杆竖着贴在桌边外侧，上夹头（红色垫块）压在底座侧面那块**带方格孔的平板**上，下夹头顶住桌板下面。
  - 底座紧贴桌边，手臂朝桌子里面伸。
- **LeRobot 源码：** 校准时终端会打印一张示意图，画的就是底座下面一个 C-clamp，夹在 table edge（桌边）上。[so_follower.py](https://github.com/huggingface/lerobot/blob/v0.7.0/src/lerobot/robots/so_follower/so_follower.py)
- **官方物料清单：** 单臂配 Table Clamp 2pcs，参考链接是 6 寸木工夹；主从两臂一套配 4pcs，是扳机式棘轮夹（TAODAN）。淘宝参考价约 ¥5–8 一个。[SO-ARM100 BOM](https://github.com/TheRobotStudio/SO-ARM100)
- 另一个实验室（UT Dallas 的 IRVL）的搭建文档也写着 "Clamp both sides of the SO-101 follower arm to the edge of the table"，也就是两侧都夹在桌边。[IRVL 搭建文档](https://irvlutd.github.io/VLAReplica/setup-docs/hardware-assembly/)

**具体步骤**

1. **准备夹子：** 2 个 4–6 寸的扳机快速夹，或者 F 夹、G 夹。开口要大于「桌板厚度 + 底座平板厚度」，喉深（夹头到杆的距离）最好有 5 cm 以上，才能伸到平板上。
2. **摆位置：** 把底座放在桌边，**格栅平板的外缘和桌边对齐**，手臂朝桌子里面。控制板那一侧对着桌外，方便接线。
3. **夹左右两块格栅平板，各用一个夹子：**
   - 上夹头压在平板靠桌边的位置，下夹头顶住桌板底面。
   - 夹头下面垫一块布或橡胶，拧到「用手推底座推不动」就够了，**不要拧死**，不然会把 PLA 打印件压裂。
4. **不要夹的地方：** 舵机、会转动的肩部（shoulder pan 那一层），以及线缆。确认肩部转一整圈不会碰到夹子的杆。
5. **桌子要求：** 实木或厚板；桌边要有一圈能让下夹头顶住的边。玻璃桌、桌边很厚的桌子、带裙边的桌子都不行。
6. **检查：** 手扶着手臂伸直，快速左右转一下肩部，底座不能翘，也不能滑。

**不行的做法：** 双面胶、只靠自重都不行。手臂伸直快速运动时，底座会翘起来甚至翻倒，还可能把串联线扯松。

**替代方案：** 桌子没法夹的话，用 4 颗 M4×30（或 M5）螺栓加翼形螺母，把底座锁在一块木板上，再把木板夹在桌边或压上重物。这套五金来自官方 4040 型材底座的文档，那份文档写的是 SO-100 的底座；SO-101 底座的孔位是否一样还没核实，用之前先对一下孔。[4040 底座说明](https://github.com/TheRobotStudio/SO-ARM100/blob/main/Optional/4040_Base_Mount/README.md)

### 1. 核对电压（插拔任何线之前先拔 DC 电源）

**我们这只臂（2026-11-16 用户核对标签）：是从臂（末端是夹爪），6 个舵机全是 STS3215 7.4V、减速比 1/147（C046）→ 用卖家附送的电源：YX-07250，输出 7.2V 5A，圆孔插头内正外负（两只臂各送一个，型号相同）。7.2V 低于舵机 7.4V 额定电压，可以用；比 5V 力矩更大。** 这不是官方从臂配置（官方从臂是 6 个 1/345 的 C001），1/147 是官方主臂手腕和夹爪用的型号。好掰，适合当遥控器；但输出力矩只有 1/345 的大约 147/345 ≈ 43%，真机自己抓东西时肩部可能撑不住、只能拿很轻的东西。舵机的磁编码器在输出轴上，所以读到的角度不受减速比影响。

**驱动板（2026-11-16 照片核对）：Waveshare Bus Servo Adapter (A) V1.1，两个黄色跳线帽已在 B（USB）位。** 板上印着「DC 9~12.6V」，那是这块板面向 12V 舵机的标称输入；板子不稳压，电源电压直接给舵机，我们的 7.4V 舵机**不要**照这个印字接 9–12V，用附送的 7.2V 适配器。圆孔 DC 插座和绿色接线端子（DC+ / DC−）是同一路电源，二选一接，不要同时接。

| 舵机标签 | 版本 | 配什么电源 |
| --- | --- | --- |
| C001（1/345）、C044（1/191）、C046（1/147） | 7.4V | **5V** 电源 |
| C018 / C047 | 12V | **12V、5A 以上**电源 |

- 电压配错会烧舵机：12V 电源接 7.4V 舵机可能烧掉；5V 接 12V 舵机会力矩不足。
- Waveshare 板子没有稳压，输入多少伏就直接给舵机多少伏。
- Waveshare 板的两个跳线帽插在 **B（USB）** 位。
- 真正的急停是拔 DC 电源。拔 USB 不会让舵机断电。

### 2. 装软件、找端口

```bash
conda create -y -n lerobot python=3.12
```

```bash
conda activate lerobot && pip install 'lerobot[feetech,core_scripts]==0.7.0'
```

```bash
lerobot-find-port
```

- Mac 上的端口是 `/dev/tty.usbmodemXXXX`。看不到这个设备的话，装 Waveshare 的 CH343 macOS 驱动。
- 不要和 LeIsaac 共用这个环境：LeIsaac 锁定 lerobot 0.4.2，两个版本的类名、校准文件目录和角度单位都不一样。

### 3. 设电机 ID（只在需要时做；不用拆臂）

- **先判断要不要设：** 运行 `lerobot-calibrate --robot.type=so101_follower --robot.port=/dev/tty.usbmodemXXXX --robot.id=my_follower`。
  - 报 `Missing motor IDs`：说明 ID 没设好，接着做下面的设置步骤。
  - 直接出现中位姿态的示意图：说明 ID 已经设好，可以直接往下做校准。
- **注意：** 这条命令不是只读的。回车以后它会往舵机的 EEPROM 里写校准数据。如果只想确认 ID，在第一个提示处按 Ctrl-C。
- **设 ID 的步骤：**
  1. 拔掉 DC 电源，把舵机之间的 3-pin 串联线拔开，每次只让一个舵机连在控制板上。
  2. 运行 `lerobot-setup-motors --robot.type=so101_follower --robot.port=/dev/tty.usbmodemXXXX`。
  3. 程序按 gripper(6) → wrist_roll(5) → wrist_flex(4) → elbow_flex(3) → shoulder_lift(2) → shoulder_pan(1) 的顺序提示。每次提示前，把控制板的线换接到对应的那一个舵机，确认电源接好后再回车。
  4. 每设完一个就贴个标签。全部设完后恢复串联：控制板 → 1 → 2 → … → 6。
- 如果是商家装好的成品臂（比如 Seeed 的 Assembled 版），可能已经设好 ID，先问商家。[LeRobot SO-101 文档](https://huggingface.co/docs/lerobot/so101) · [Seeed 第 7 章](https://wiki.seeedstudio.com/robotics/soarm_physical_ai_course_chapter_7/)

> **2026-11-16 实测（臂 A）：** 6 个舵机全是出厂 ID 1，接在一起互相冲突，扫描只偶尔看到 ID 1。臂已组装好，没有按官方那样逐个单接，而是用 [tools/so101_assign_ids.py](tools/so101_assign_ids.py) 沿串联链设 ID：先拔开 1→2，把 1 号临时改成 ID 100；之后设第 k 号时接回 (k−1)→k、拔开 k→(k+1)，把唯一的新 ID 1 改成 k；最后把 100 改回 1。共拔 5 根线。注意：只拔 1→2、后面不拔，会让 2–6 号同时上总线继续冲突。只读检查用 [tools/so101_scan.py](tools/so101_scan.py)。

### 4. 校准

1. 再跑一次上面的 `lerobot-calibrate`。
2. 按终端示意图摆好中位姿态：上臂竖直，前臂和夹爪水平朝前，夹爪半开。回车。
3. 把每个关节慢慢扫到两端的机械极限。wrist_roll 是整圈电机，不用扫。
4. 校准文件存在 `~/.cache/huggingface/lerobot/calibration/robots/so_follower/my_follower.json`。

### 5. 第一次上力矩：小步动一下

`max_relative_target=5` 限制每一步最多走 5°，`shoulder_pan` 一共转 10°。

```python
import time
from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

robot = SO101Follower(SO101FollowerConfig(port="/dev/tty.usbmodemXXXX", id="my_follower", max_relative_target=5.0))
robot.connect()
target = {k: v for k, v in robot.get_observation().items() if k.endswith(".pos")}
target["shoulder_pan.pos"] += 10
for _ in range(50):
    robot.send_action(target)
    time.sleep(0.02)
robot.disconnect()  # 默认会关力矩，手臂会掉下来，用手托住
```

### 6. 没有主臂怎么遥控

- 用 LeRobot 官方的手机遥操作：iOS 装 HEBI Mobile I/O，Android 用浏览器打开脚本给的网址。
- 准备工作：
  1. git clone LeRobot 源码，并 checkout v0.7.0（examples 不在 pip 包里）。
  2. 把 `SO-ARM100/Simulation/SO101` 复制到 `examples/phone_to_so100/`。
  3. 在脚本里把 PhoneOS 改成你的手机系统。
  4. 然后运行 `teleoperate.py`。
- **启动前清空工作区：** 脚本一启动就会把手臂移到 homing 位姿。[手机遥操作文档](https://huggingface.co/docs/lerobot/phone_teleop)

### 把从臂当主臂，遥控 Isaac 里的机械臂（2026-11-15 读代码确认）

**技术上可以，但这不是官方设计的用法，我们还没实测。**

**为什么可以：** LeIsaac 读主臂的代码（`devices/lerobot/so101_leader.py` 和远程版的 `so101_joint_state_server.py`）只做一件事：关掉力矩，然后读 ID 1–6 这 6 个 STS3215 舵机的当前位置。代码不区分主臂和从臂。从臂设好 ID 并上电后，在它看来和主臂一样。

**比键盘好在哪：** 这样录到的是关节角数据，正好是 LeIsaac 和 ACT、SmolVLA 这些策略需要的格式。键盘录的末端增量动作做不到这一点。

**要注意的：**
1. **推起来很沉：** 从臂 6 个舵机都是 1/345 减速比；主臂的大多数关节是 1/191 或 1/147，就是为了用手推起来轻。用手推从臂会比较费力，动作也不够顺。长期反推高减速比的舵机会不会加快齿轮磨损，没有找到资料，推断有可能。
2. **没有扳机：** 夹爪只能直接用手掰钳口来开合。
3. **校准会被覆盖：** LeIsaac 会用自己的校准文件（存在 `scripts/environments/teleoperation/.cache/<id>.json`），并把零点写进舵机的 EEPROM，这会覆盖 LeRobot 的校准。以后要把它当从臂用时，要重新跑一次 `lerobot-calibrate`。
4. **一次只能当一种角色：** 被当作主臂用的时候，它就不能同时作为真机去执行动作。

**怎么接（仿真在 AWS 上，手臂插在 Mac 上）：**
1. 在 Mac 上，LeIsaac 源码目录里：

   ```bash
   pip install "source/leisaac[remote]"
   ```

   ```bash
   python scripts/environments/teleoperation/so101_joint_state_server.py --port /dev/tty.usbmodemXXXX --id my_follower_as_leader --rate 50
   ```

   第一次运行会自动进入校准：先摆中位、回车，再把每个关节扫到两端。
2. 安全组没有对外开 5556 端口，所以要在 Mac 上开一个 SSH 反向隧道：

   ```bash
   ssh -R 5556:localhost:5556 ubuntu@<AWS 公网 IP>
   ```

3. 在 AWS 上运行：

   ```bash
   python scripts/environments/teleoperation/teleop_se3_agent.py --task=LeIsaac-SO101-LiftTakeoutBox-v0 --teleop_device=so101leader --remote_endpoint=tcp://localhost:5556 --num_envs=1 --device=cuda --enable_cameras
   ```

   要录数据就再加 `--record`。

### 以后要把仿真动作发给真机

- 单独建一个 `lerobot==0.4.2` 环境，在那里重新校准一次。
- 动作要先经过 LeIsaac 的 `convert_leisaac_action_to_lerobot()` 转换，再用 `use_degrees=False` 发送。
- 同一条臂不要混用多套校准工具（LeRobot、LeIsaac、Seeed GUI），它们会互相覆盖舵机 EEPROM 里的校准。
- 仿真里的脚本抓取把机器人重力关掉了（`disable_gravity=True`）。所以仿真成功不代表真机在负载下也能保持姿态。

## 三、GPT 补物理属性：怎么做才站得住

脚本在 [tools/estimate_physics.py](tools/estimate_physics.py)，离线测试在 [tools/test_estimate_physics.py](tools/test_estimate_physics.py)，已通过 5 项。真实的 LLM 请求还没跑过。

**它做什么：**
1. 读取 Lux3D 网格，算出包围盒、表面积和体积。
2. 把照片和这些尺寸发给支持图像的 LLM，要求返回 JSON：材料、是否空心、壁厚、质量、静/动摩擦、弹性。
3. 采样 5 次，丢掉格式不对或数值离谱的回答，取中位数。
4. 用「材料表 × 几何」交叉检查质量，差 2 倍以上就标记为需要人工复核。
5. 摩擦夹在材料表的合理范围内。
6. 只往 USD 里写显式质量，并把 LLM 的原始回答和推理过程记进资产，方便放进报告。

```bash
export LLM_BASE_URL=<OpenAI 兼容地址>/v1 LLM_API_KEY=<key> LLM_MODEL=<支持图像的模型>
```

```bash
python tools/estimate_physics.py --glb experiments/2026-11-08-lux3d-takeout-box/g1_standard/raw_mesh.glb --photo experiments/2026-11-08-lux3d-takeout-box/input/takeout_box_input.png --name "paper takeout box" --samples 5 --out physics_v1.json
```

照片会发给第三方 LLM。key 只从环境变量读取，不要写进代码或日志。

**四个坑（都已核实）：**
1. **空心物体：** Lux3D 的网格是封闭的实心体。如果只给密度，0.8 L × 纸板密度会算出约 0.56 kg，而真实约 30 g，差约 20 倍。必须让 LLM **直接估质量**，并且只写显式质量；USD 里显式质量优先于「密度 × 体积」。
2. **摩擦是两种材料之间的值，不是单个物体的属性。** 倾斜实验测到的是「纸盒 × 手指材料」这一对。仿真里物体、手指、桌面三者的摩擦和合成方式（PhysX 默认取平均）要和实测对应起来。不能一边把手指固定成 1.0，一边拿平均后的值去和实测比。
3. **仿真夹爪比真机强很多：** LeIsaac 里夹爪力矩上限是 10 N·m，真机被 LeRobot 限到最大扭矩的 50%，5V 供电下估计只有约 0.7–1.0 N·m。做两档接近真机的力矩版本，否则仿真成功率会偏乐观。
4. **跑对任务：** 默认任务 `LiftTakeoutBox-v0` 加载的是缩到 5.5 cm 的小盒。改了真实尺寸版的参数后，要跑 `LiftTakeoutBox-Real-v0`，否则看不到变化。小盒在物理上已经是另一个物体。更好的做法是换一个真实尺寸本来就能放进 6–7 cm 开口的物体（纸杯、小药盒），这样称重、倾斜实验和真机抓取才对得上。

**报告里的迭代对比：**

| 版本 | 质量和摩擦从哪来 | 要测什么 |
| --- | --- | --- |
| v0 | 手填（0.02 kg、0.6/0.5） | 下落测试、滑动起始角 |
| v1 | GPT 估计（5 次采样的中位数和离散程度） | 同上，再加「质量 × 摩擦」网格上的抓取成功率 |
| v2 | 真实测量：厨房秤称重，倾斜实验 μs = tanθ | 同上，并和真实滑动角对比 |

- 做网格扫描时，每一格要用固定的质量和摩擦，不能用随机区间。
- 引用文献数字时写「质量估计误差约 2 倍量级（大件家居物数据集）」。PhysBench 的「物体属性」类别：GPT-4o 56.91%，人类 97.10%。[PhysBench](https://arxiv.org/html/2501.16411)

## 四、4 天排期

| 日期 | 仿真主线（AWS L4） | 真机（Mac） | 报告和素材 |
| --- | --- | --- | --- |
| 11/15 | 开机，跑通官方状态机示例 | 固定 → 核对电压 → 设 ID → 校准 → 小步测试 | 称重、做倾斜实验（v2） |
| 11/16 | 写 LiftObject 状态机，抓起外卖盒；接入 GPT 物理属性 | 手机遥操作抓一次，录视频 | 跑 GPT 估计（v1） |
| 11/17 | 5–10 个 Lux3D 物体批量测试，做 v0/v1/v2 对比 | — | 可选：InteriorGS 餐厅场景（见 PARTNER-RESOURCES.md） |
| 11/18 | 可选：50 条示范训 ACT；冻结代码 | — | 录 demo 视频，写报告 |
| 11/19 | — | — | 19:00 前提交，发小红书 |

## 需要你确认的事

1. **有没有主臂（leader，带手柄的那只）？** 有的话，真机可以录真正的示范数据。
2. ~~舵机标签是 C001 还是 C018/C047？~~ 已确认：6 个全是 STS3215 7.4V 1/147；电源是附送的 7.2V 5A 适配器。
3. 这台臂是自己组装的，还是商家装好的？（决定要不要设电机 ID）
4. 手边有没有 F 夹或 C 夹？桌子是什么材质、多厚？
5. 有没有摄像头（一个正面，加一个腕部可选）？以后真机跑学习策略必须有。
6. 用哪个 LLM 提供商？脚本假设是 OpenAI 兼容接口，有的提供商不支持 `response_format`。
