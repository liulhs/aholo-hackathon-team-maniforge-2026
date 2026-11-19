# 网页 Demo：图生抓取 · Image2Grasp

访客把物体拖到垫子上任意位置，机械臂用学来的策略自己把它拿起来。全部在浏览器里跑：

- **物理：** 官方 MuJoCo WebAssembly 版 `@mujoco/mujoco` 4.0.1，和 Python 训练、评估用的是同一个版本，加载的是同一个编译好的模型。
- **策略：** 不看图像的 ACT 模型，导出成 ONNX，用 `onnxruntime-web` 在 CPU（WebAssembly）上跑，每帧预测一次再做时间平均，和 `sim/evaluate.py --temporal-ensemble 0.01` 一致。
- **画面：** three.js 直接读编译后模型里的网格、贴图和材质，每帧从 MuJoCo 拷贝位姿。

## 本地运行

```bash
cd web && npm install && npm run dev
```

打开 http://localhost:5173 。`npm run build` 生成静态站点到 `web/dist/`，任何静态托管都能放，路径是相对的（`base: './'`），放在子目录下也能用。

## 线上地址

**魔搭创空间：** https://www.modelscope.cn/studios/liulhs/image2grasp （公开，静态 SDK，免费 CPU）。2026-11-19 下午部署。

更新办法：`npm run build`，把 `web/dist/` 同步到本地克隆 `deploy-modelscope/`（不进本仓库 git），`web/deploy/modelscope-README.md` 复制成那里的 `README.md`，提交后 `git push`（用户名 `oauth2`，密码是魔搭访问令牌），再在创空间页面重新部署或「重启」。大文件（wasm、onnx、mjb.gz、sog、mp4、图片）走 git-lfs。

## 页面要的文件从哪来

| 文件 | 怎么生成 | 进 git |
| --- | --- | --- |
| `public/policy/policy.onnx`、`policy.json` | `python sim/export_policy.py <checkpoint>/pretrained_model --out-dir web/public/policy --eval <评估结果...>` | 进 |
| `public/scenes/<物体>.mjb.gz`、`manifest.json`、`thumbs/` | `OMP_NUM_THREADS=4 python sim/build_web_assets.py --out-dir web/public/scenes --verify` | 只进 manifest 和缩略图；场景文件按需重新生成 |

`--verify` 证明网页用的场景和训练场景物理完全相同：逐字段比较，并把录过的示范在网页场景上逐位重放。网页场景只改了外观：物体和机械臂的显示网格减了面、贴图缩到 1024 像素。

## 代码结构

- `src/sim/simulation.ts`：一个物体的抓取场景，对应 Python 的 `lift_scene.py`、`teleop.SimArm`。物体状态（12 个数）按 MuJoCo `mju_quat2Mat` 的公式逐项计算，尺寸取 manifest 里存的值。
- `src/policy/`：ONNX 推理和时间平均（从 LeRobot 0.7.0 的 `ACTTemporalEnsembler` 逐行移植），每帧交给策略的物体状态（`observation.ts`，按 `policy.json` 的 `object_position` 给底面中心或重心）。
- `src/demo/attempt.ts`：一次抓取的判定，和 `sim/evaluate.py` 同一套规则，另外要求抬起保持的 1 秒里物体不碰桌子。
- `src/render/sceneView.ts`：three.js 画面、拖动和点击的拾取。
- `src/main.ts`：载入、实时循环、拖放、切换物体。

## 交互

- 拖动物体换位置，松手后机械臂开始抓；也可以直接点垫子上的空位。
- 机械臂起始姿态下夹爪停在垫子靠近底座的一小块上方。放在那里的物体会被自动往外挪一点（manifest 的 `start_pose_keepout` 加运行时的接触检查）。
- 键盘：先 Tab 到画面，方向键移动物体 1 厘米，Enter 开始，R 转 45°。

## 餐厅背景（2026-11-19 下午）

桌子周围的餐厅是群核 SpatialVerse 公开的 [SAGE-3D_InteriorGS_usdz](https://huggingface.co/datasets/spatialverse/SAGE-3D_InteriorGS_usdz) 场景 839920（CC BY-NC 4.0），用 3D 高斯泼溅表示，只用于显示，不参与物理。原版 [InteriorGS](https://huggingface.co/datasets/spatialverse/InteriorGS) 的使用条款禁止再分发，所以不用它。

- **生成：** `python sim/sage3d_background.py data/sage3d/839920.usdz --spot 1.3 -3.6 --yaw-deg 139.5 --out data/sage3d/restaurant_839920.ply`，再 `cd web && npx splat-transform ../data/sage3d/restaurant_839920.ply public/background/restaurant_839920.sog`。脚本从 .usdz 里的 3DGRUT `.nurec`（gzip + msgpack，float16）读出 120 万个高斯，截取空地 (1.3, −3.6) 周围 6 米内的 50.7 万个，只留 0 阶颜色，平移旋转到仿真坐标（地面在 −0.74 米，桌子中心在空地上）。`.sog` 6 MB，不进 git。
- **渲染：** `src/render/sceneView.ts` 的 `loadBackdrop` 动态载入 Spark 2.4.0（MIT，2.7 MB），和 MuJoCo 的网格画在同一个 three.js 场景里。开着时地面换成只接阴影的透明面，雾关掉。
- **何时载入：** 电脑上演示开始后自动载入；手机和触屏默认不载入，点「餐厅背景」才载入。
- **速度：** Playwright 驱动的 Chrome 里开着背景 73 帧/秒，关着 143 帧/秒，仿真都保持实时。

## 重试和物体位置输入（2026-11-19 下午）

### 页面现在的设置

- **模型：** `outputs/act_state_all8_com`，八个物体 340 段示范。物体位置输入是**重心**（`policy.json` 的 `object_position: "com"`），不是物体底面中心。数据集用 `python sim/build_state_dataset.py --object-position com --name all8_com` 从录好的数据直接算，不用重录。
- **重试（`src/demo/attempt.ts`）：** 一轮 12 秒内没抓起来，或物体倒在桌上已经 6 秒，就结束这一轮。机械臂用 1.5 秒平滑退回起始姿态（脚本控制，不用策略），等 10 帧，清空策略的动作历史，从物体当前位置重新抓。最多再试 3 次。最后一轮物体倒了也给满 12 秒；抬起保持的那 1 秒里到了时限，让它保持完。
- **代码：** `src/demo/frame.ts` 是每一帧的驱动（策略 / 退回 / 不动 → 物理 → 判定），`src/policy/observation.ts` 决定每帧交给策略的 12 个数。两者页面和 `tools/eval_browser.ts` 共用。`npm test` 跑 `tests/` 下的单元测试。

### 实测（页面设置，八个物体各 100 次，同一批摆放）

| 模型 | 不重试 | 重试 |
| --- | --- | --- |
| 底面中心作位置（`act_state_all8`） | 614/800（77%） | 655/800（82%） |
| 底面中心 + 倒地适配（见下） | | 710/800（89%） |
| **重心作位置（`act_state_all8_com`，页面现在用的）** | 671/800（84%） | **721/800（90%）** |

- **重心模型各物体（重试）：** 外卖盒 96、Aholo 吉祥物 95、GO 3S 93、星星人 92、Labubu 91、X5 86、拓麻歌子 85、AirPods 83。没抓住的几乎都是物体倒了。
- **配对比较（同一批摆放，符号检验）：**
  - 重心比底面中心：不重试时 114 次只有重心抓起、57 次只有底面中心抓起，p<0.001；重试时 108 比 42，p<0.001。
  - Python 里 400 次相同尝试：339 比 323（85% 比 81%），76 次结果不同（46 比 30），p=0.08，偏弱。
  - 重心模型（721）对「底面中心 + 倒地适配」（710）：差别在误差内。
  - 两种输入各只训练了一次，训练本身的随机波动没测。
- **真 Chrome 里复测：** 每个物体前 25 次摆放在页面里（Playwright 驱动的 Chrome 157，用页面自己的模块）抓起 178/200，Node 里同样摆放 184/200，逐次结果 192/200 相同；不同的 8 次里 7 次是 Node 抓起、Chrome 没有（p≈0.07），浏览器里可能略低一点，没查实。浏览器和 Node 的 WebAssembly 计算在最后一位上会有差别（追踪到第 35 帧一个关节角差 1e-17 rad），经过接触放大后个别尝试结局不同。

### 为什么改成重心（11/19 下午的诊断）

用户看到的现象：机械臂碰到物体后，还在原地去抓。四个实验，每个都由另一个代理用原始数据复核过。脚本和结果在 `outputs/eval/diag/`：

1. **模型每帧都看物体当前的位置，不是只看初始位置。** 把立着的物体在伸手途中瞬移 5 厘米，夹爪会追过去：89 次里 78 次在 4 秒内到了新位置 2 厘米内，第一次合夹爪时离旧位置 2 厘米内的只有 6 次。时间平均会让它晚约 0.5–1 秒转向：LeRobot 的 `ACTTemporalEnsembler` 给**旧**预测更大权重，系数 0.01 时最近 0.5 秒的预测只占 21% 权重。
2. **但原来的位置输入是物体的底面中心**（自由关节原点 `qpos[0:3]`），重心在它上方 2.3–4.9 厘米。物体倒下后两者水平相距 2–5 厘米。碰倒后的 837 次合夹爪里，夹爪离底面中心中位 2.7 厘米，离重心 4.1 厘米（正常抓立着的物体时是 0.6–0.8 厘米）。高的物体（Labubu、X5）倒下时底面中心几乎不动（中位 1.5 厘米），重心移了约 5.6 厘米，所以看起来像在原地抓。
3. **物体一开始就躺着时，原模型 160 次只抓起 39 次**（立着时是 122 次）。不重新训练，只在推理时改输入：只换成重心的水平位置 61 次（p=0.01）；把躺着的物体描述成「立在重心处、长边沿躺着的长轴、尺寸用躺着时实际长宽高」的盒子，70 次（p<0.001）。这就是上表的「倒地适配」，代码在 `src/policy/lyingAdapter.ts`，只对底面中心模型生效。
4. **改成重心不用重录：** 重心 = 原点 + R·ipos，可以从已存的位置和朝向直接算。立着时重心只是底面中心加一个固定高度，所以只在物体倾斜、被夹起、倒下的帧上有区别。
5. **审查后修的一处：** 起初页面和 `evaluate.py` 从 MuJoCo 的 `data.xipos` 读重心，`mj_step` 之后它比位置晚一个子步（5 毫秒），物体在动时差约 1 毫米，和训练数据（按当前位置算）对不上。现在三处都用同一个公式（和 `xipos` 刷新后差 6e-17 m，和训练数据差 3e-8）。修之前测的是 728/675/339，修之后 721/671/339，结论不变。

剩下的问题：没抓住的几乎都是物体倒了。示范里只有约 2.6% 的帧是物体倒在桌上而手臂没碰它，录一些「把倒了的物体抓起来」的示范应该还能再提高。

## 实测（2026-11-19 凌晨，五个物体的旧模型）

- **浏览器代码路径和 Python 一样好。** `tools/eval_browser.ts` 在 Node 里用页面自己的模块（`Simulation`、`TemporalEnsembler`、`Attempt`、`placeObject`）加 onnxruntime-web 和 MuJoCo WebAssembly，重放 `sim/evaluate.py` 的同一批 500 次尝试：抬起 372 次，Python 里 ONNX 模型是 366 次。逐次看约 10% 的尝试结果不同（PyTorch 和 ONNX 在 Python 里互相比也是这个比例），总数在误差内。
- **按页面的设置，成功率 69%。** 机械臂固定在一个起始姿态，物体在垫子上均匀随机放、随机朝向，每个物体 100 次，共 500 次抬起 344 次：Labubu 59、星星人 73、AirPods 79、Aholo 吉祥物 65、拓麻歌子 68。没抓住的 156 次里 126 次是物体被碰倒，30 次是 20 秒超时。当时页面显示的是这个数。比 Python 评估的 74% 低，原因没查实：固定起始姿态已排除（用同一姿态重放 Python 的尝试仍是 74%），可能是放置分布不同（Python 评估重抽压到机械臂的位置，页面把物体往外挪）。
- **碰倒了不立刻判失败。** 策略有时能把碰倒的物体再抓起来（同一批 500 次里 372 次成功中有 48 次是这样），所以页面和 `evaluate.py` 一样给满 20 秒，状态显示「碰倒了，还在试」。一碰倒就判失败（1.5 秒后）时，同样设置的 300 次只有 63%。
- **速度：** 一帧（一次策略推理加 10 步物理）在 Node 里中位 2 ms，20 帧每秒的预算是 50 ms。
- **大小：** 首次打开要下载约 51 MB（MuJoCo 7 MB、onnxruntime 15 MB、策略 17 MB、一个物体的场景 11–14 MB），托管方对 .wasm 做 gzip 时约 33 MB。之后切换物体每个再下 11–14 MB。`npm run build` 最后一步 `tools/strip-wasm-debug.mjs` 去掉 MuJoCo .wasm 里约 4 MB 的调试信息（只给调试器用，代码不变；去掉前后第一次抓取的结果和用时完全相同）。
- **浏览器物理和 Python 不是逐位一致：** 确定性的，单帧差约 1e-11，遇到接触时可能放大到毫米级，所以上面的成功率是在浏览器代码路径上直接测的。
- **代码审查（11/19 凌晨）：** 三个方向独立审查、每条再由另一个代理反驳，24 条里 14 条成立，都已修掉并复测。重点两条：点一下被举着的物体或按 Enter 会不重置场景就开始新一轮，算出 1 秒的假成功；连点两个物体卡片时，高亮的和实际载入的不一致。
- **还没测：** 真浏览器里的 Safari、Firefox、微信内置浏览器和真机手机；以上浏览器测试都是 Chrome（Playwright）或 Node。需要 iOS 16.4 以上（解压场景用的 DecompressionStream）。

```bash
cd web && npx tsx tools/eval_browser.ts page --per-object 100 --objects labubu --out ../outputs/eval/web/all8/com_labubu.json   # --retries 0 不重试；--policy 换模型目录；--lying-adapter false
```
