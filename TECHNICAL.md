# Lux3D 资产进入 Isaac Lab 的工程调研

核查日期：2026 年 11 月 7 日

**建议先做一件事：让操作员在 Isaac Lab 里抓起一个由 Lux3D 生成的商品，并回放这次操作。** 这条路径让赛事要求的 Lux3D 直接决定操作对象，也能检验 Cogway 最关心的问题：换一个商品后，能否用同一套工作站继续采集有效操作数据。单件刚体和桌面已经足够验证这一点。整间餐厅的 3DGS 重建可作为第二个实验。[赛事规则](https://www.aholo3d.cn/hackathon) · [Cogway 遥操作任务研究](../research/teleop_accessible_work_evidence.md)

本次实际读取了四个官网展示资产的 GLB 文件头和完整 JSON 块。下文关于 API 的结论来自官方规范，关于接入的建议来自 Isaac Lab 源码和已发表的案例。本次未调用计费生成接口，未运行 Isaac Sim、Isaac Lab 或策略训练。

## Lux3D 能交付什么

Lux3D 的图生、文生 3D 面向单件物体。G1 能输出包含模型和贴图的 ZIP、GLB 网格，并可额外请求 Gaussian PLY。G1-Turbo 按请求选择输出，具体结果以任务返回为准。多格式导出是单独的步骤，可把已有 GLB 或 Lux3D ZIP 转为 USDZ、OBJ 等格式。尺寸可以用 AI 预测；G1 接口还可通过 `customSize` 以毫米指定模型高度。对于要夹取的实物，建议用实测宽度和高度检查生成结果，再核对夹爪开度。[Lux3D 国内开发文档](https://lux3d.aholo3d.cn/docs) · [单物体生成说明](https://labs.aholo.ai/api-docs/skills/lux3d) · [编辑器设置](https://aholo.featurebase.app/en/help/articles/1087651-lux3d-website-navigation-homepage-and-creation-space) · [官方接口规范](https://labs.aholo3d.cn/api-docs/openapi.json)

### 图生 3D 接受什么输入（2026-11-18 核对）

11/18 第一次生成 Labubu、星星人、AirPods 时只传了一张图，没有先查输入规格，AirPods 的结果很差。下面是事后核对的结果，来源是[官方接口规范](https://labs.aholo3d.cn/api-docs/openapi.json)、[帮助文档](https://aholo.featurebase.app/en/help/articles/1087651-lux3d-website-navigation-homepage-and-creation-space)和网页工作台（`3d.aholo.cn/studio`）上的实际界面。

- **图片数量：** 1–32 张（接口字段 `imgs`，保留顺序）。G1 和 G1-Turbo 都支持多图。
- **第一张是主图：** 工作台原话是「首张图片将作为主图（用于材质还原），其余图片仅作视角参考，每次仅生成一个模型」。所以主图要选光线最好、最能代表外观的那张，其余图片提供侧面和背面的形状。
- **格式：** PNG、JPG、JPEG、WEBP。
- **对图片的要求：** 单个物体、轮廓完整、背景干净、光线均匀。官方点名会降低稳定性的情况：严重遮挡、主体太小、多个物体重叠、高反光造成的过曝。
- **AI 多视图补全：** 上传一张图后，工作台有「AI 多视图补全」按钮，24 积分一次，约 1 分钟，补出 4 张 1024×1024 的图。接口是 `image-to-four-view`，四张的顺序是正面斜侧、反向斜侧、侧面、背面。补出来的图会自动加到主图后面，一起作为输入。
- **其他可调项：** 标准版 / 极速版；面数 100K / 200K / 300K（接口是 1 万到 30 万）；是否生成 PBR 贴图；去除背景；尺寸用 AI 预测或自定义高度。
- **费用：** 标准版生成 20 积分一次（有限免次数时先扣限免）。
- **结论：** 有同一物体的多角度实拍图时，按「主图 + 侧面 + 背面」上传；只有一张图时，先做 AI 多视图补全再生成。不要只传一张图。

### 四个公开 GLB 样品

从官网首页取得展示文件，读取 glTF 2.0 的节点、网格、图元、材质、扩展和附加属性。三角面数由三角形图元的索引数除以三得到。四件都只有一个节点、一个网格和一个 PBR 材质，包含法线和纹理坐标。JSON 中均未见动画、关节、碰撞形状、质量、惯量或摩擦参数。这个结果限于这四个样品。其他专用接口的产物需要另行检查。[Lux3D 官网](https://lux3d.aholo3d.cn/)

| 官网展示分类 | 三角面数 | 原始文件 |
| --- | ---: | --- |
| 游戏 | 97,170 | [GLB](https://qhstaticssl.kujiale.com/model/gltfbinary/1789464470636/E55A62B32363620A10F9427C0CD9C24D.glb) |
| 3D 打印 | 284,022 | [GLB](https://qhstaticssl.kujiale.com/model/gltfbinary/1789464470638/DA67A8BEC024FE69B84B96994EA89B1F.glb) |
| 建筑 | 293,858 | [GLB](https://qhstaticssl.kujiale.com/model/gltfbinary/1789464466835/4F92083EB11044978A16B64361EB5451.glb) |
| 影视 | 98,095 | [GLB](https://qhstaticssl.kujiale.com/model/gltfbinary/1789464466836/D0070BB684CF86EB452E8B5E602BA5F3.glb) |

对抽屉、带盖容器等多部件物体，Lux3D 另提供拆件和关节动画接口。拆件返回 GLB；关节化接收 GLB 和运动提示词。官方查询接口的成功示例分别给出 ZIP 和 GLB 占位链接，实际输出格式由任务决定。公开规范未承诺可供 PhysX 直接使用的关节轴、行程、摩擦或驱动参数。做开盖实验时，验收应是机器人施力后盖子绕正确轴运动，并停在规定角度。[Aholo API 能力](https://labs.aholo.ai/api-docs/intro) · [关节化和结果格式规范](https://labs.aholo3d.cn/api-docs/openapi.json)

## 路线一：单物体 mesh → 刚体 USD → Isaac Lab 抓取

1. **从一个有实物参照的商品开始。** 拍摄一个刚性小纸盒，记录三边、质量和正面方向。由 Lux3D 生成外观网格，保存原始文件、输入图和尺寸。将模型放到用米表示的工作站，检查轴向、中心、桌面高度、初始姿态和夹爪开度。
2. **分开处理外观与碰撞。** 保留带纹理的网格用于相机渲染。纸盒用按实测尺寸建立的长方体作碰撞体，赋予刚体、质量和接触材质；更复杂的形状才评估凸包或凸分解。质量来自实测或明确标记的假设，摩擦可先设置合理区间，再通过滑动和抓取实验校准。PBR 里的粗糙度描述反光，指尖与盒子的摩擦需要单独配置。[NVIDIA 刚体与碰撞示例](https://docs.isaacsim.omniverse.nvidia.com/latest/replicator_tutorials/tutorial_replicator_object_based_sdg.html)
3. **选一个明确的导入入口。** 可把 Lux3D 追加导出的 USDZ 作为视觉层，在外层 USD 配置碰撞、刚体、语义标签和坐标。也可追加导出 OBJ/FBX，走 Isaac Lab 2.3.1 自带的 `convert_mesh.py`，它支持指定碰撞近似和质量。该版脚本列明的输入是 OBJ、STL、FBX；拿到 GLB 时应选择支持 GLB 的转换器或先走 Lux3D 多格式导出。两条方式都需在目标 Isaac 版本核对单位、贴图和碰撞位置。[Lux3D 导出格式](https://github.com/manycore-research/ComfyUI-Lux3D#lux3d-multi-format-export) · [Isaac Lab 2.3.1 转换脚本](https://github.com/isaac-sim/IsaacLab/blob/v2.3.1/scripts/tools/convert_mesh.py)
4. **复用任务再替换物体。** 先跑通对应版本自带的 Franka Lift 基线。它用 `RigidObjectCfg` 和 `UsdFileCfg` 指定被抓取的物体。复制该任务配置，替换对象并调整台面上的出生高度、抓取位置和成功条件。首个闭环应展示自由落体、桌面接触、夹爪闭合、抬起、释放和重置。[官方 Lift 对象配置](https://github.com/isaac-sim/IsaacLab/blob/v2.3.1/source/isaaclab_tasks/isaaclab_tasks/manager_based/manipulation/lift/config/franka/joint_pos_env_cfg.py) · [任务注册及可用控制方式](https://github.com/isaac-sim/IsaacLab/blob/v2.3.1/source/isaaclab_tasks/isaaclab_tasks/manager_based/manipulation/lift/config/franka/__init__.py)

## 路线二：3DGS 环境 → 静态碰撞层 → 可交互场景

**先分清物体和环境的来源。** Lux3D 的 Gaussian PLY 可以描述一个生成物体。整间房的视觉背景则可用 Aholo SpatialGen 生成，或用 Aholo Reality / World 重建已有空间。World 文档列出多图、视频和全景视频等重建输入，输出可含 PLY、SPZ 和 LOD 元数据。想复现特定工位，建议采集实际空间并设置尺度参照。生成一间视觉上合理的房间适合做环境变化，实物位置和距离仍需要现场测量确认。[Aholo World 与 Lux3D 的区别](https://labs.aholo.ai/api-docs/intro) · [SpatialGen 输入与导出](https://reality.aholo.ai/resources/tutorials/how-to-create-3d-world-ai-spatial-gen)

**静态环境已有可用工具。** Aholo Viewer 的 `splat-transform` 可从 3DGS 生成体素占用数据，开启相应选项还能生成 `collision.glb`，供行走、贴地和避障查询使用。可将这个网格作为地面或墙壁的静态碰撞初稿，再转换为 Isaac 的碰撞层。验证桌面高度、窄通道和遮挡处，检查虚假的障碍或洞。把需要移动的商品从背景中分离，以独立的刚体重新放入，避免物体拿走后背景里留下一份影像或碰撞体。[Aholo Viewer 碰撞文件与用途](https://aholojs.dev/zh-CN/manual/physics-collision/)

**已有同主办方的实证。** 群核科技和浙大的 SAGE-3D 将室内 Gaussian PLY 转为可在 Isaac Sim 渲染的 USDZ，另外载入同一房间的碰撞 USD，最后编成 USDA 场景。论文的碰撞体来自原始 mesh 的凸分解，导航还使用语义标注、占用图和轨迹。这个案例说明混合表示可行，也指出任意新场景需要补的输入。该工作验证了导航，其结果不能直接证明指尖接触或精密抓取的精度。[SAGE-3D 实现与处理步骤](https://github.com/Galery23/SAGE-3D_Official#-sage-3d-scene-data-preparation) · [ICLR 论文，附录 D](https://openreview.net/pdf?id=HB6KvsqcAn) · [NVIDIA NuRec](https://developer.nvidia.com/omniverse/nurec)

NVIDIA 另有公开流程，把 Marble 的高斯场景与单独的碰撞网格对齐，在 Isaac Sim 中让移动机器人行驶。教程包含校准地面和真实尺度的步骤，可以借鉴；其输入来自 Marble，Lux3D 的具体导出仍须验证。[NVIDIA 场景导入教程](https://developer.nvidia.com/blog/simulate-robotic-environments-faster-with-nvidia-isaac-sim-and-world-labs-marble/)

在我们的目标 Isaac 版本上应逐项测 RGB、任务需要的深度或分割、碰撞和机器人接触。尤其要检查 splat 外观、代理几何和标签在同一相机视角中是否对齐。复用公开项目之前先核对其运行版本，SAGE-3D 场景渲染示例要求 Isaac Sim 5.0 或以上；上文的 Lift 代码链接固定在 Isaac Lab 2.3.1。[SAGE-3D 环境说明](https://github.com/Galery23/SAGE-3D_Official) · [NVIDIA 相机输出与渲染后端](https://docs.nvidia.com/isaaclab/concepts/sensors/camera)

## 训练数据的验收

| 用途 | Cogway 要补什么 | 首次验收看什么 |
| --- | --- | --- |
| 感知训练，如检测纸盒 | 相机和照明、对象语义、随机化范围、相机标定 | 输出 RGB 与所需深度、掩码或包围盒。把标签叠回图像，检查遮挡处的边界和实例编号。[Replicator 场景数据示例](https://docs.isaacsim.omniverse.nvidia.com/latest/replicator_tutorials/tutorial_replicator_scene_based_sdg.html) |
| 模仿学习，如从人类示范学抓取 | 机器人控制接口、操作员或脚本、每步时间同步、成功定义、回放环境 | 一条完整 episode 有初始状态、逐步观测和动作、终止状态及成功标签。回放时检查抓取和释放的位置。[Isaac Lab 录制与回放](https://isaac-sim.github.io/IsaacLab/v2.3.1/source/overview/imitation-learning/teleop_imitation.html) |
| 强化学习，如在不同摆位下学会抬起 | 动作与观测空间、奖励、终止、可重复重置以及独立的评估场景 | 记录训练步数和策略版本，在固定评估种子上比较基线与训练后成功率。单次脚本演示只能证明执行流程。[Isaac Lab Lift 训练配置入口](https://github.com/isaac-sim/IsaacLab/blob/v2.3.1/source/isaaclab_tasks/isaaclab_tasks/manager_based/manipulation/lift/config/franka/__init__.py) |

**建议的首轮对照**：先用原生方块检查仿真和控制，再用真实尺寸相近的 Lux3D 商品重复相同的抓取条件。分别记录导入、接触、抬升、重置和轨迹回放结果。若两组在同一阶段失败，先查机器人或任务；若只有生成商品失败，优先回查坐标、碰撞几何、夹爪开度和摩擦。留下完整失败轨迹，有助于决定接下来该改哪一层。
