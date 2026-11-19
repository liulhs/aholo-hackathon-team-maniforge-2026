# 2026-11-15 · CPU 可行性验证：MuJoCo + SO-101 + Lux3D 外卖盒

**结论：** 只用 CPU（M4 Pro，单线程），MuJoCo 就能让 SO-101 夹起 Lux3D 生成的外卖盒；同一段动作放到浏览器用的 WASM 版里重放，结果完全一致。不需要 GPU。

## 结果

| 项目 | 数值 |
| --- | --- |
| 仅机械臂，Python mujoco 4.0.1 | 约 1250 倍实时 |
| 机械臂 + Lux3D 盒子（减面到 4k 面） | 约 770 倍实时，编译 40 ms |
| 同上，Node 里跑 WASM 版 `@mujoco/mujoco` 4.0.1 | 约 440 倍实时，编译 27 ms |
| 盒子落在地面后 | 中心高度 z = 0.0246 m（半高 0.025 m），速度约为 0，稳定直立 |
| 脚本抓取（逆运动学求关节角 + 合爪 + 抬起） | 盒子从 z = 0.0246 抬到 0.1416，**抬高 11.7 cm**。WASM 重放结果逐位一致 |
| 物理参数扫描（锥形外卖盒） | 质量 0.03–1.0 kg、摩擦 0.1–0.8 全部抬起 |
| 物理参数扫描（同尺寸的普通方块） | 只有 1 kg 且摩擦 0.1 时抬不起来 |

## 要点和坑

- **碰撞只用凸包：** MuJoCo 的网格碰撞一律用凸包（Menagerie 默认凸包最多 128 个顶点）。所以杯子、碗这类凹物体会被当成实心块，要先做凸分解（CoACD，或者 Lux3D 自带的拆件接口）。
- **STL 有面数上限：** STL 解码器最多支持 200,000 个面，Lux3D 原始网格有 27.6 万面，要用 OBJ 格式或先减面。物理效果和减面无关，因为碰撞用的是凸包。
- **摩擦要设优先级才生效：** Menagerie 的夹爪碰撞体 `priority=1`。物体要设 `priority=2`，LLM 估的摩擦才会用在指尖接触上。物体同时要设 `condim="6" solref="0.01 1"`，因为优先级高的一方会连 condim、solref 一起覆盖，不设的话夹爪原本调好的接触参数就丢了。
- **外卖盒参数几乎不影响结果：** 锥形外卖盒会被两个钳口卡住，所以质量、摩擦几乎影响不了抓取成败。如果想让物理属性在 Demo 里看得出效果，要换成普通方块类物体，或者降低夹爪力。
- **抓取起点不是从零开始：** 抓取是从 Menagerie 自带的 `pickup` 关键帧出发的，那时夹爪已经在物体旁边。机械臂从远处任意位置接近物体，还没测过。

## 怎么复现

脚本假设 Menagerie 的 SO-101 模型放在 `models/so101/`。为了不把 18 MB 的 STL 放进仓库，这个目录没有一起保存。

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/google-deepmind/mujoco_menagerie downloads/mujoco_menagerie
```

```bash
cd downloads/mujoco_menagerie && git sparse-checkout set robotstudio_so101 && cd ../.. && mkdir -p models && cp -r downloads/mujoco_menagerie/robotstudio_so101 models/so101
```

```bash
python3 -m venv .venv && .venv/bin/pip install mujoco==4.0.1 trimesh scipy fast_simplification pillow
```

```bash
.venv/bin/python prep_object.py ../2026-11-08-lux3d-takeout-box/g1_standard/raw_mesh.glb models/so101/assets && cp assets/plain_box.obj models/so101/assets/ && .venv/bin/python spike.py && .venv/bin/python grasp.py
```

WASM 测试：先运行 `npm i @mujoco/mujoco@4.0.1 --ignore-scripts`，然后运行 `node wasm_test.mjs`。

## 文件

| 文件 | 作用 |
| --- | --- |
| `prep_object.py` | 处理 GLB：缩到最宽 5 cm，Y 轴朝上转成 Z 轴朝上，居中，减面 |
| `scene_builder.py` | 把物体作为可自由移动的刚体加进场景：质量 0.03 kg，摩擦 0.8 |
| `spike.py` | 测速度和落地稳定性 |
| `grasp.py` | 用逆运动学（DLS）走路径点完成抓取 |
| `sweep*.py` | 扫描质量和摩擦对抓取的影响 |
| `grasp_ctrl.json` | 录下的控制序列，用于 WASM 重放 |
| `wasm_test.mjs` | Node 里用 WASM 版加载并重放 |
| `scenes/` | 生成的场景文件 |
| `assets/` | 减面后的盒子、对照用的普通方块 |
| `renders/` | 离屏渲染图 |
