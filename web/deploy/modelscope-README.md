---
domain:
- multi-modal
tags:
- robotics
- embodied-ai
- mujoco
- so-101
- lux3d
- aholo
deployspec:
  entry_file: index.html
license: Apache License 2.0
---

# 图生抓取 · Image2Grasp

图生 3D，再到图生抓取：Lux3D 从照片生成物体，机械臂从人的示范里学会抓它。

把物体拖到垫子上任意位置，SO-101 机械臂用学来的策略自己把它拿起来。全部在你的浏览器里运行，不需要服务器算力：

- **物理：** MuJoCo 官方 WebAssembly 版 4.0.1，和训练用的是同一个版本、同一个编译好的场景。
- **策略：** 不看图像的 ACT 模型（740 万参数），输入是机械臂 6 个关节角和物体的重心位置、朝向、大小；导出成 ONNX，用 onnxruntime-web 在 CPU 上运行。
- **物体：** 8 个物体用 Lux3D 由照片生成 3D 模型，缩放到夹爪能抓的大小。
- **示范：** 用一只真实的 SO-101 机械臂当遥控器，在仿真里抓了 340 次。

按这个页面的设置随机摆放 800 次，抓起 721 次（90%）；一轮没抓到，机械臂会退回起点，从物体现在的位置重新抓，最多再试 3 次。没抓住的几乎都是物体先被碰倒了。

首次打开要下载约 50 MB（物理引擎、推理引擎、模型和一个物体的场景），之后切换物体每个再下 11–14 MB。

页面下方有完整的制作过程：每个物体的 Lux3D 参考图与生成结果、真实机械臂遥操作仿真的对照视频、示范采集、每一步改动的成功率，以及全部参考资料。

演示里桌子周围的餐厅背景来自群核 SpatialVerse 公开的 SAGE-3D_InteriorGS_usdz 场景 839920，许可是 CC BY-NC 4.0，只用于非商业展示；本空间其余代码按 Apache License 2.0。

Aholo 黑客松参赛作品（Team ManiForge）。
