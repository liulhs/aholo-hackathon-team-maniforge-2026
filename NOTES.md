# 开发记录（比赛期间的交接文档）

> 这是比赛期间给接手者看的工作记录，按时间保留了调研、实测和失败原因。项目介绍见 [README.md](README.md)。规则分析、交付清单和竞品调研等内部文档没有公开，下文提到时不再给链接。

资料核实于 2026-11-07。赛事截止于 **2026-11-19 19:00（北京时间）**。当前进度：选题调研完成。2026-11-08 已用 Lux3D 实际生成一个外卖盒并检查了输出；2026-11-13 已在 AWS 上跑通 Isaac Sim 5.1 + LeIsaac + SO-101，外卖盒能稳定放在桌上，WebRTC 推流能看到画面（见下方[进度记录](#进度记录)）。遥操作抓取和录数据还没做。

| 接手时想知道什么 | 去哪里看 |
| --- | --- |
| Lux3D 能输出什么，四个样品里有什么，mesh 和高斯分别怎样进入仿真 | [技术调研与依据](TECHNICAL.md) |
| 能不能做一个只用 CPU 的网页在线 Demo（浏览器 MuJoCo + SO-101 + Lux3D） | [网页 Demo 方案](WEB-DEMO.md) · [CPU 验证](experiments/2026-11-15-mujoco-cpu-spike/README.md)（2026-11-15） |
| 有没有现成的 SO-101 抓取模型、真机怎么上电和固定、GPT 补物理属性怎么做 | [SO-101 下一步](SO101-NEXT-STEPS.md)（2026-11-15） · [tools/estimate_physics.py](tools/estimate_physics.py) |
| 抓取训练怎么做（人示范 + ACT，MuJoCo 为主、LeIsaac 保底） | [抓取训练计划](TRAINING-PLAN.md)（2026-11-16） |
| 驱动板安装板 STL、驱动板装在机械臂哪里 | [硬件打印件](hardware/README.md)（2026-11-16） |
| 上线 Isaac Sim 前要避开哪些坑，机器现在什么状态、怎么重新开机 | [踩坑汇总](gotchas/README.md) · [AWS 接手手册](cloud-setup/AWS-RUNBOOK.md) |
| Isaac Sim、Isaac Lab、LeIsaac、GR00T、ACT 分别是什么 | [Isaac 部署栈图解](learning/isaac-stack.html)（[在线版](https://claude.ai/artifact/3bFiGg19YnjAkvSVXcxhPU)） |
| 当时看到的是哪场活动 | [用户提供的赛事首页截图](references/aholo-hackathon.png) · [赛事官网](https://www.aholo3d.cn/hackathon) |

## 用户的设想与建议选题

用户希望用 Lux3D 创建训练数据：从 mesh 或 3D 高斯出发，组成一个能在 Isaac Lab 中训练机器人的场景。**「餐厅收桌」是本次调研给出的建议，仍待团队定题。** 选它的理由是，Cogway 已经有相应的真实岗位和试点素材，可以具体判断一条仿真轨迹有没有价值。整屋高斯路线的现有工具、适用场景和缺口保留在技术调研中。

Cogway 希望让人跨越地点和身体条件的限制参与现场工作。公司把远程操作员与第三方机器人之间的连接、安全控制和任务记录视为自己的基础设施。项目材料第 5 页把培训和轨迹、异常、结果列入运营流程，第 12 页描述真人示范与人工修正，第 14 页把模拟培训、认证、跨场地复制和介入率列为后续验证事项。[公司使命](../web/src/components/mission/Mission.astro) · [技术定位](../web/src/components/stack/LayerStack.astro) · [Cogway 项目材料](../Cogway_Pitch_Deck_20260818_V2.0.pptx)

Brooklyn 的 Cuci Burger 试点视频包含迎宾、收桌和倒水。建议把收桌动作缩到「夹起一个轻质外卖盒，移至回收区」。让操作员在仿真中复现一次抓滑、纠正抓法，下一位操作员就有一条可以回放和练习的案例。视频可作为岗位背景；训练所需的同步画面、机器人状态和动作还需另外采集。[试点视频](../MVP%20video.mp4) · [素材说明](../site-direction/HANDOFF.md) · [收桌画面](../site-direction/assets/mvp_bussing.jpg)

## 接手后的第一个实验

**前两天只验证一个盒子能否稳定抓起。** 记录所用 GPU 环境、Isaac Sim 和 Isaac Lab 版本。找一个轻质盒子，拍同一物体的多个角度，量高度和重量，用 Lux3D 生成带材质的 GLB，并保存输入、生成设置、原始资产和版本。把盒子接入已有的 Franka Lift 示例，做成独立刚体，校准尺度、朝向、碰撞形状、质量与摩擦。[Lux3D 开发文档](https://lux3d.aholo3d.cn/docs) · [Isaac Lab Franka Lift 配置示例](https://github.com/isaac-sim/IsaacLab/blob/v2.3.2/source/isaaclab_tasks/isaaclab_tasks/manager_based/manipulation/lift/config/franka/joint_pos_env_cfg.py)

用真实运行画面检查四件事：盒子能落稳在桌面、夹爪能抓起、松手后会落下、重置后能再次执行。留下每次尝试的初始摆位、结果，以及碰撞形状叠加在可见模型上的截图。若失败，先定位尺度、坐标或接触几何；这比重建整间餐厅更快暴露技术链路的问题。

通过首测后再扩到几种盒型和摆位，加入回收区与成功判定。记录每回合的相机画面、机器人状态、动作、接管时刻、成功或失败原因。演示可以直接串起 **真实盒子 → Lux3D 资产 → 抓取失败 → 人工纠正 → 轨迹回放**。保留生成和迭代素材，方便写比赛要求的项目报告。

如果进一步声称「这些数据改善了策略」，用示范训练一个小策略，保留未参与训练的盒型和摆位，比较同一批测试条件下的成功次数和总尝试次数。若想评估 Lux3D 纹理带来的收益，策略必须读取图像；直接给策略物体坐标的实验只能检验状态控制。录到数据、训练出策略、迁移到真实机器人，是三个需要分别出示证据的结果。[Lift 默认观测](https://github.com/isaac-sim/IsaacLab/blob/v2.3.2/source/isaaclab_tasks/isaaclab_tasks/manager_based/manipulation/lift/lift_env_cfg.py) · [Isaac Lab 示范采集](https://isaac-sim.github.io/IsaacLab/v2.3.1/source/overview/imitation-learning/teleop_imitation.html)

## 进度记录

### 2026-11-08 · Lux3D 图生 3D 实测：外卖盒

文件都在 [experiments/2026-11-08-lux3d-takeout-box](experiments/2026-11-08-lux3d-takeout-box/)，检查脚本在其中的 `tools/`。

- **输入：** Wikimedia Commons 的 CC0 图片 [Sweet Sour-Boxes-Large.jpg](https://commons.wikimedia.org/wiki/File:Sweet_Sour-Boxes-Large.jpg)，裁出左侧合盖的中式外卖盒，放大到 930×1005，蓝色背景（`input/`）。
- **操作：** 在 Lux3D 网页工作台（图生 3D）里，用同一张图各跑一次标准版和极速版，参数都是默认值。内置浏览器加载不了 `qhstaticssl.kujiale.com` 上的脚本，所以改用 Claude in Chrome。
- **消耗：** 标准版按钮显示 20 积分，用的是限免次数；极速版显示 0 积分。完成后账号仍是 300 积分，限免显示还剩 4 次。生成过程中限免一度显示为 2 次，原因没有核实。

| | 标准版（任务 33631） | 极速版（任务 33646） |
| --- | --- | --- |
| 接口记录的设置 | `lux3d_g1`、`standard`、`outputFormat: [glb, ply]`、300K 面、PBR | `lux3d_g1`、`fast`、`outputFormat: [ply]`、3DGS |
| 耗时 | 约 5.6 分钟 | 约 21 秒 |
| 产物 | `result.zip`、`textured.glb`，另有中间产物 `raw_mesh.glb` 和 `gaussian.ply` | 只有 `gaussian.ply` |

**各文件的实测结果：**

| 文件 | 内容 | 能否用于仿真 |
| --- | --- | --- |
| `textured.glb`（14 MB） | 27.6 万面，2K 基础色贴图 + 金属/粗糙度贴图，包围盒 0.111 × 0.120 × 0.120 m，原点在包围盒中心 | 外观很好；焊接后仍有 172 条非流形边和 18 个重复面，不封闭，不宜直接作碰撞体 |
| `raw_mesh.glb`（6.6 MB） | 同一几何的未贴图版本，**封闭、流形、单一连通块**，体积 0.80 L，约为凸包体积的 82%；元数据写着 `predictUnit: m`、`yup: true`、`scale: 0.1195` | 最适合做碰撞体或凸分解；但它是网页任务记录里的中间产物，官方 API 规范里没有这个输出 |
| `result.zip`（17 MB） | `MODEL.glb`（贴图只是一张 80 字节的占位图）+ 6 张渲染器贴图（漫反射、反射、反射光泽、菲涅尔、折射、折射光泽） | 面向群核自家渲染器；进 Isaac 用 `textured.glb` 更直接 |
| 标准版 `gaussian.ply`（78 MB） | 114 万个高斯，只有 0 阶球谐颜色（不随视角变化），包围盒 0.104 × 0.128 × 0.120 m | 坐标轴和 GLB 不一致，渲染出来上下颠倒，叠加前要先对齐 |
| 极速版 `gaussian.ply`（147 MB） | 216 万个高斯，字段相同，包围盒 0.135 × 0.141 × 0.110 m | 同上；尺寸和标准版不一致 |

**结论：**
1. **网格质量够用：** 外观、图案和折痕都还原得不错（`renders/g1_textured_4views.png`）。几何干净的版本是 `raw_mesh.glb`，带贴图的版本在烘焙贴图后引入了拓扑缺陷。
2. **背景会进贴图：** 盒顶内侧发蓝，是原图的蓝色背景被烘焙进了贴图。正式实验要用白色或中性背景拍照。
3. **尺寸要自己校准：** 网格的最长边被缩放到 0.12 m，两次 PLY 的尺寸也互不相同，都不是实测值。
4. **贴图粗糙度只管渲染：** 粗糙度贴图平均 0.11，比真实纸盒亮得多；这只影响渲染，摩擦仍要在 Isaac 里单独设。
5. **结果链接无需登录：** `qhsmodel.kujiale.com` 上的 GLB 和 PLY 链接不带签名，用 curl 不登录也能下载，有链接的人都能拿到文件；ZIP 链接带签名，2 小时后过期。

### 2026-11-18 · Lux3D 再生成三个物体：Labubu、星星人、AirPods 充电盒

详见 [experiments/2026-11-18-lux3d-objects](experiments/2026-11-18-lux3d-objects/README.md)。

- **结果：** 三个都生成成功（标准版、300K 面、PBR，任务 45003 / 45010 / 45012，各约 6–7 分钟），用了 3 次限免，积分仍是 2,100。Labubu 和星星人效果好；AirPods 充电盒表面有噪点，厚度比实物厚约一倍。
- **输入：** Labubu 和星星人用的是泡泡玛特官网商品图（有版权，用户知情后决定使用）；AirPods 用 Wikimedia Commons 的 CC0 照片。
- **转换：** `sim/prep_object.py` 已把三个转成 MuJoCo 资产（`sim/models/objects/`）。还没接进抓取场景，没录示范。
- **第二轮改用多视角输入（同一天）：** 第一轮只传了一张图，AirPods 表面全是噪点、厚度是实物的两倍。查了输入规格后（图生 3D 可传 1–32 张图，第一张是主图；只有一张图时可先做「AI 多视图补全」，见 [TECHNICAL.md](TECHNICAL.md)），三个物体用多视角重新生成（任务 45073 / 45061 / 45057），都更好，AirPods 改善最大。花了 64 积分，剩 2,036，限免用完。后续用 `labubu_mv`、`twinkle_devil_mv`、`airpods_open_mv`。
- **晚上又加了四个（同一天）：** Aholo 吉祥物、拓麻歌子、Insta360 X5、Insta360 GO 3S，都用多视角生成（任务 47870 / 47862 / 47887 / 47903）。吉祥物、X5、GO 3S 效果好；拓麻歌子一般（挂链成了碎块，背面错了）。花了 152 积分，剩 1,884。
- **八个物体都接进了 MuJoCo 抓取场景：** `sim/lift_scene.py`（原 `takeout_scene.py`）按物体生成场景，`mjpython sim/record.py --object <名字>` 录制，每个物体一个数据集。物体都立着放，质量均匀、碰撞体底面压平，只保证放下时能立住，被夹爪碰到会倒（试过底部配重，后来按用户要求去掉了），见 [sim/README.md](sim/README.md)。36 个测试通过；去掉配重后（11/19 凌晨）八个物体都重测了不连真臂的脚本录制回放，各 2 回合，逐位一致。这个脚本里手臂没有碰到物体，只覆盖了物体静置在桌面上的情况。
- **真臂示范开始录了（11/19 凌晨）：** Aholo 吉祥物 40 回合、Labubu 40 回合，`python sim/replay.py --object <名字>` 全部逐位一致；每个物体约 20 分钟。物体在桌上被碰歪超过 37 度的回合：吉祥物第 0、3、9，Labubu 第 37，训练时去掉。之后录完了星星人、AirPods、拓麻歌子，五个物体各 40 回合，全部逐位一致。外卖盒、Insta360 X5、GO 3S 还没录。
- **第一个不看图像的模型（11/19 凌晨）：** 五个物体合训一个 ACT（740 万参数，30000 步，MPS 约 21 分钟），在 MuJoCo 里自己抓，500 次随机尝试抬起成功 **74%**（各物体 69–76%）。只用每个物体 20 个示范时是 38%。LeRobot 默认不归一化物体状态，打开后从 65% 升到 72%。失败几乎都是在桌上把物体碰倒。评估脚本经过独立审查，修掉了「手臂起始姿态压在物体上」等问题后才出的这些数。命令和明细见 [sim/README.md](sim/README.md)。
- **网页 Demo 跑通（11/19 凌晨，未部署）：** `web/` 下的静态页面，浏览器里用官方 MuJoCo WebAssembly 4.0.1 跑物理、onnxruntime-web 跑策略、three.js 画面；访客拖动或点击放物体，机械臂自己抓，物体从卡片架切换。策略导出成 ONNX（17 MB），和 PyTorch 输出差 1.2e-6 rad，在 Python 里闭环 500 次抬起 366 次（PyTorch 369 次）。网页场景和训练场景的物理字段完全相同，200 个录制回合在网页场景上逐位重放。浏览器物理和原生 Python 不是逐位一致（确定性的，接触时差异可放大到毫米级），所以在 Node 里用页面自己的代码直接测：Python 的同一批 500 次尝试抬起 372 次；按页面设置（固定起始姿态、物体随机放在垫子上）500 次抬起 344 次（69%），页面上显示的就是这个数。场景文件从每个 73 MB 减到 11–14 MB（只减显示网格，物理重新验证过）。代码经过独立审查，14 个问题已修。**还没部署，还没在 Safari、微信和真机手机上测过。**做法和文件来源见 [web/README.md](web/README.md)。
- **八个物体合训，加重试（11/19 中午）：** 外卖盒 60 回合、两个 Insta360 各 40 回合录完，八个物体共 340 回合合训一个 ACT（同样设置，40000 步，约 30 分钟），Python 里 400 次抬起 323 次（81%；原来五个物体在新模型上 80%，旧模型 74%）。网页加了重试：一轮 12 秒没抓起来，或物体倒在桌上 6 秒，机械臂用 1.5 秒退回起始姿态，策略从物体当前位置重新抓，最多再试 3 次。按页面设置 800 次：不重试 614 次（77%），重试 655 次（82%），页面显示 82%。剩下的失败几乎都是物体倒了抓不起来：示范里没有抓倒地物体的例子。明细见 [web/README.md](web/README.md)。
- **位置输入改成重心（11/19 下午）：** 用户发现机械臂碰倒物体后还在原地抓。诊断（四个实验各自复核）：模型每帧都看物体当前位置，但给的是物体底面中心，倒下后离物体中间 2–5 厘米，夹爪就合在那里。从已录数据直接算出重心作位置输入、重新训练（不用重录），按页面设置 800 次：不重试 77%→84%，重试 82%→**90%**（p<0.001）；Python 同一批 400 次 81%→85%（p=0.08）。页面现在用这个模型；在真 Chrome 里复测 200 次抓起 178 次，Node 同样摆放 184 次。明细见 [web/README.md](web/README.md)「重试和物体位置输入」。
- **网页完善并部署到魔搭（11/19 下午）：** 改名「图生抓取 · Image2Grasp」。页面下方加了完整的项目介绍（Lux3D 迭代、真机遥控示范的手机实拍视频和屏幕录像、成功率随改动的变化、底面中心改重心的调试故事、老实说、工具与素材来源），演示桌子周围加了群核 SAGE-3D / InteriorGS 的餐厅场景（3D 高斯泼溅，CC BY-NC 4.0，只当背景）。公开地址：https://www.modelscope.cn/studios/liulhs/image2grasp 。做法见 [web/README.md](web/README.md)。

### 2026-11-13 · Isaac Sim 首次跑通：SO-101 + Lux3D 外卖盒

上线包、脚本和手册在 [cloud-setup](cloud-setup/README.md)，冒烟测试截图和结果在 [experiments/2026-11-13-isaac-smoke](experiments/2026-11-13-isaac-smoke/)。

- **机器：** AWS 首尔 g6.2xlarge（NVIDIA L4 24 GB、8 vCPU、30 GiB 内存），实例 `<instance-id>`，公网 IP 当时是 `<public-ip>`（停机已释放，开机会换新 IP），系统是 Canonical 纯净 Ubuntu 22.04（`ami-079679697f41501ee`），按需 $1.20/时。安全组只放行 `<home-ip>`（直连）和 `<vpn-ip>`（VPN 出口）。
- **版本：** NVIDIA 驱动 580.196.07，Isaac Sim 5.1.0（pip），IsaacLab @`3c6e67b`（0.47.2），LeIsaac @`24d3bcd`，PyTorch 2.7.0 cu128，Python 3.11。
- **资产：** `cloud-setup/build_takeout_box_usd.py` 从 Lux3D 产物生成：外观用 `textured.glb`，碰撞体用 `raw_mesh.glb` 的凸包。质量 0.02 kg、摩擦 0.6/0.5 都是假设值。小号版缩到最宽 5.5 cm，因为 SO-101 夹爪的有效开口实测只有约 6–7 cm（从 USD 碰撞网格计算）。
- **冒烟结果：** 无界面运行 240 步后，小号盒的盒底高度 0.0406 m，真实尺寸盒 0.0404 m，桌面 0.041 m，两者都在桌上停稳。官方方块停在 0.056 m，即桌面加半个边长，也停稳了，但被判成 FAIL：判定按“原点在盒底”写，不适用于原点在中心的方块，是脚本问题。
- **推流：** Mac 用 Isaac Sim WebRTC Streaming Client 1.1.5 连上，看到了画面（2026-11-13 22:3x），用户已练习键盘遥操作。键盘控制有一个按键卡住的缺陷，已用 `cloud-setup/patches/so101_keyboard_held_keys.patch` 修复，修复后的版本还没再测过。**还没录数据。**
- **状态：** 2026-11-13 23:16（北京时间）已停机，环境保留在 200 GB 硬盘上（停机期间只收硬盘费）。重新开机后公网 IP 会变：VPN 的直连规则、推流客户端里的地址和 `ssh` 命令都要换成新 IP。

**踩过的坑（都已修进脚本）：**

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| Isaac Sim 一启动就在 `librtx.scenedb` 段错误 | AWS 深度学习镜像预装 595 驱动；Isaac Sim 5.1 验证的是 580 分支。580.65.06 在 6.8 aws 内核上编译失败，而且镜像开机会强制装回 595 | 改用纯净 Ubuntu，装 580.196.07（`install_driver.sh`） |
| 渲染器报 CUDA 非法内存访问后卡死 | 纯净 Ubuntu 缺 `libGL` 等运行库，渲染器的材质库 `libneuray` 加载失败 | 装 libgl1、libglu1-mesa 和 X11 运行库 |
| IsaacLab 没装上却被标成完成 | `flatdict==4.0.1` 用新版 setuptools 构建失败，`isaaclab.sh` 仍返回成功 | 先用 setuptools<81 构建 flatdict，装完逐个检查 pip 包 |
| 测试显示 PASS 实际报错 | Kit 吞掉 Python 异常仍返回 0；脚本放在 `~/cogway/`，被误当成 `leisaac` 包导入 | 测试脚本移到 `tools/`，按结果文件判定成败 |
| 动作配置缺失 | 创建环境前要先 `use_teleop_device` | 测试里先指定键盘 |
| 客户端连得上但一直黑屏 | 推流扩展用错了（`omni.kit.livestream.webrtc`）；IsaacLab 2.3 要用 `--livestream 1` + `PUBLIC_IP` | `run_teleop.sh` 已改；另外 VPN 不转发 UDP，要给服务器 IP 加直连规则 |

### 2026-11-16 · 真机臂 A：设舵机 ID、主臂模式校准

- **环境：** Mac（M4 Pro），conda 环境 `lerobot`（Python 3.12），`lerobot[feetech,core_scripts]==0.7.0`（舵机通信走 rustypot 1.13.1）。驱动板 Waveshare Bus Servo Adapter (A) V1.1 被识别为 `/dev/tty.usbmodem5B910285391`，macOS 自带驱动即可。电源 YX-07250 7.2V。
- **问题：** 6 个舵机全是出厂 ID 1。8 种波特率全扫都没有稳定应答，ID 1 约 1/20 次有回。只接 1 号时 ID 1 稳定应答，证实是 ID 冲突。
- **处理：** 臂已装好，用 `tools/so101_assign_ids.py` 沿串联链逐个设 ID（方法见 [SO101-NEXT-STEPS.md](SO101-NEXT-STEPS.md) 第 3 节），每次写入前先扫描核对。结果 ID 1–6 全部应答，型号都是 777（STS3215）。
- **校准：** `lerobot-calibrate --teleop.type=so101_leader --teleop.id=arm_a`。按主臂模式校准，因为这只臂当遥控器用，全程不上力矩。校准文件 `~/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/arm_a.json`。各关节原始范围（0–4095）：shoulder_pan 887–3124，shoulder_lift 838–3178，elbow_flex 847–3059，wrist_flex 858–3190，gripper 1649–2860，wrist_roll 整圈。`SO101Leader.get_action()` 读出角度（默认单位是度），收拢姿态下约为 pan 3°、lift −102°、elbow 97°、wrist_flex 54°。
- **MuJoCo 遥控已打通（同日）：** 仓库根目录 `.venv`（Homebrew Python 3.13，mujoco 4.0.1 + lerobot 0.7.0），Menagerie SO-101 @`370c439`，运行 `mjpython sim/teleop.py` 时真臂带动仿真里的手臂，偏差 1° 以内。启动步骤见 [sim/README.md](sim/README.md)。
- **方向已确认：** 用户在 `--mirror` 模式下逐个关节掰过，6 个关节方向都对，`JOINT_MAP` 不需要修正。第二只臂还没设 ID、没校准。以后要让这只臂当从臂自己动，需要按 `so101_follower` 另外校准一次。

## 当前证据边界

- 已在用户的 Chrome 阅读赛事页、FAQ、Lux3D 工作区和官方文档；已检查四个官网公开 GLB 样品，并核对群核参与的 SAGE-3D 导航先例。证据与链接见上方两份记录。
- 已用用户账号实际生成一次标准版和一次极速版（见进度记录）。
- 2026-11-13 已在 Isaac Sim 5.1 里加载外卖盒并验证它能稳定停在桌上，WebRTC 推流也已打通；还没有用遥操作抓取、录数据或训练。当前 Cogway 工作区可见官网、试点资料和技术调研，未找到可直接复用的 Isaac Lab 任务、机器人仿真资产或示范轨迹集。其他仓库及 GPU 环境尚未盘点。
- 团队报名/组队、正式选题、提交状态都未核实。赛事素材赛后用于商业训练及衍生数据分发的授权也待确认，详见赛事记录（未公开）。
