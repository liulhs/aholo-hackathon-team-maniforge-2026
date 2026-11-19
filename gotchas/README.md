# 踩坑汇总

整理于 2026-11-14，覆盖 2026-11-07 至 11-13 的 Lux3D 测试、云端选型和 Isaac Sim 上线。每条写明现象、原因和处理；标“已修进脚本”的，`cloud-setup/` 里的脚本已经处理，照手册走不会再遇到。机器现状、重新开机步骤和还没解决的问题见 [../cloud-setup/AWS-RUNBOOK.md](../cloud-setup/AWS-RUNBOOK.md)。

## 一、Lux3D 与 Aholo

| # | 现象 | 原因 | 处理 |
| --- | --- | --- | --- |
| 1 | `lux3d.aholo3d.cn` 在 Claude 内置浏览器里白屏 | 页面脚本放在 `qhstaticssl.kujiale.com`，内置浏览器拦截（`ERR_BLOCKED_BY_CLIENT`）；本地放行后也没生效 | 改用自己的 Chrome（Claude in Chrome） |
| 2 | 限免次数从 5 次跳到 2 次，完成后又变回 4 次 | 网页按“计费项”计次，生成过程中会先占用；标准版最终扣 1 次，极速版显示 0 积分 | 以完成后的余额为准，不看生成中的数字 |
| 3 | 结果文件谁都能下载 | `qhsmodel.kujiale.com` 上的 GLB、PLY 链接不带签名，不登录也能下载；只有 ZIP 带签名，2 小时过期 | 不想公开的物体别用；结果要及时存到本地 |
| 4 | ZIP 里的 `MODEL.glb` 没有贴图 | 它的贴图只是一张 80 字节的占位图，真正的材质是另外 6 张渲染器专用贴图 | 进仿真用 `textured.glb` |
| 5 | `textured.glb` 不封闭 | 烘焙贴图后多出 172 条非流形边和 18 个重复面 | 碰撞体改用 `raw_mesh.glb`（封闭、流形）；它只出现在网页任务记录里，官方 API 规范没有列出 |
| 6 | 盒顶内侧发蓝 | 原图的蓝色背景被烘焙进了贴图 | 拍照用白色或中性背景 |
| 7 | 尺寸不是真实值 | AI 预测尺寸，最长边被缩放到 0.12 m；两次生成的 PLY 尺寸也不一样 | 按实测尺寸重新缩放（`build_takeout_box_usd.py`） |
| 8 | 高斯 PLY 渲染出来上下颠倒 | PLY 的坐标轴和 GLB（Y 轴向上）不同 | 和网格叠加前先做坐标变换 |
| 9 | 官网影视样品的底座中空 | 底座里有一个法线朝内的内壳，体积几乎等于底座包围盒 | 质量不能用网格体积乘密度来算，要称重 |
| 10 | 原始顶点数接近甚至超过三角面数 | 网格在 UV 接缝处拆了顶点 | 做拓扑检查或凸分解前先按坐标焊接 |
| 11 | 交接文档写的 `customSize` 在图生 3D 接口里找不到 | API 规范中只有材质重绘接口有 `customSize`，图生和文生只有 `aiPredictSize` | 不指望用它控制尺寸 |
| 12 | `docs.isaacsim.omniverse.nvidia.com` 打不开 | 本地网络或代理拦截了文档站，但下载站能访问 | 直接用下载链接，例如 `https://downloads.isaacsim.nvidia.com/isaacsim-webrtc-streaming-client-1.1.5-macos-arm64.dmg` |

## 二、选云与账号

| # | 现象 | 原因 | 处理 |
| --- | --- | --- | --- |
| 13 | AWS 开不了 GPU 实例 | 新账号每个区域的 G 系列配额都是 0，按需和 Spot 都是 | 按区域提额申请；首尔 8 vCPU 约 25 分钟获批，批完再等约 30 分钟生效 |
| 14 | 配额申请显示 `CASE_CLOSED` | 这个状态不代表被拒，结论要看邮件 | 看邮件，再查配额的实际数值 |
| 15 | 删掉旧实例后马上开新的，报 `VcpuLimitExceeded` | 旧实例在关闭过程中仍占着 vCPU | `aws ec2 wait instance-terminated` 之后再开 |
| 16 | 停机后再开机连不上 | 停机会释放公网 IP，开机换新 IP | 改 VPN 直连规则、客户端地址和 SSH 地址；或绑弹性 IP（停机期间也收费） |
| 17 | CompShare 注册不了 | 只支持 +86 手机号短信登录 | 没有国内手机号就选别家 |
| 18 | CompShare 抢占式很便宜 | 但不能手动关机，不用时也计费；常显示“暂无资源” | 用按量计费 |
| 19 | CompShare 推流的前提 | 只有华北二A、上海二B 有独立 IP 和端口配置；Isaac 镜像看不出 Isaac Sim 版本 | 选这两个区，自己装 5.1 |
| 20 | 国内大厂用国际版开大陆区域 | 阿里云、腾讯云、华为云国际版都要先做实名认证 | 时间紧就不走这条路 |
| 21 | Isaac Sim 不能用某些 GPU | 不支持没有 RT 核心的 A100、H100 | 选 L4、L40S、A10、RTX 40/50 系 |

## 三、驱动与系统（最耗时的部分）

| # | 现象 | 原因 | 处理 |
| --- | --- | --- | --- |
| 22 | Isaac Sim 5.1 一启动就在 `librtx.scenedb` 段错误 | AWS 深度学习镜像预装 595 驱动；Isaac Sim 5.1 验证的是 580 分支，多人在 590/595 上遇到同样的崩溃 | 换 580 分支驱动 |
| 23 | 装 580.65.06 时内核模块编译失败（`pci_resize_resource`） | 580.65.06 不兼容 Ubuntu 的 6.8.0-1069-aws 内核 | 用 580.196.07（580 分支最新版本） |
| 24 | 在深度学习镜像上换驱动，重启后又变回 595 | 镜像的 `nvidia-kmod-load` 服务开机会装回自带驱动；删除旧 DKMS 模块时还把同名的 `nvidia.ko` 一起删了；EFA、`nvidia_fs` 等模块占着驱动卸不掉 | **不要用深度学习镜像**，用纯净 Ubuntu 22.04 + `install_driver.sh`（已修进脚本） |
| 25 | 重启后驱动安装包不见了 | `/tmp` 在重启时会清空 | 安装包放在 `~/drv/`（已修进脚本） |
| 26 | 物理引擎报 CUDA 非法内存访问后卡死 | 纯净 Ubuntu 缺 `libGL`，渲染器的材质库 `libneuray` 加载失败，着色器跟着失败 | 装 libgl1、libglu1-mesa、libegl1 和 X11 运行库（已修进脚本） |

## 四、安装 Isaac Sim / IsaacLab / LeIsaac

| # | 现象 | 原因 | 处理 |
| --- | --- | --- | --- |
| 27 | IsaacLab 没装上 | 依赖 `flatdict==4.0.1` 只有源码包，要用 `pkg_resources`；pip 自动选用的 setuptools 84 已删掉了它 | 先装 `setuptools<81`，再用 `--no-build-isolation` 装 flatdict（已修进脚本） |
| 28 | 安装失败却被标成完成 | `isaaclab.sh --install` 出错后仍然返回成功 | 装完逐个检查 pip 包（已修进脚本） |
| 29 | 用 `import isaaclab_tasks` 做安装校验时报找不到 `omni` | 这个包要等 Isaac Sim 启动后才能导入 | 只查 pip 包信息（已修进脚本） |
| 30 | 后台安装卡住不动 | 第一次导入 `isaacsim` 时会询问是否接受 NVIDIA Omniverse 许可协议，后台没人回答 | 自检只读版本号；许可协议要由用户本人同意后，再设 `OMNI_KIT_ACCEPT_EULA=YES` |
| 31 | 安装时访问 GitHub | `isaaclab.sh --install` 默认会从 GitHub 装 rl-games | 用 `--install none`，需要训练框架时从 PyPI 装 rsl-rl（已修进脚本） |
| 32 | 内存只有 30 GiB | g6.2xlarge 低于 Isaac Sim 建议的 32 GB | 实测能跑；要多环境并行训练时换 g6e |

## 五、测试脚本

| # | 现象 | 原因 | 处理 |
| --- | --- | --- | --- |
| 33 | 报找不到 `leisaac.assets.robots.lerobot` | 测试脚本放在 `~/cogway/` 下，旁边就是仓库目录 `leisaac/`，被 Python 当成了 `leisaac` 包 | 脚本放到 `~/cogway/tools/`（已修进脚本） |
| 34 | 测试显示 PASS，实际报错了 | Kit 吞掉 Python 异常，进程仍返回 0 | 测试写结果文件，按文件判定成败（已修进脚本） |
| 35 | 报动作配置缺失（`actions.arm_action`） | LeIsaac 要先调用 `use_teleop_device()` 才会填好动作配置 | 创建环境前先指定 `keyboard`（已修进脚本） |
| 36 | 方块任务被判失败，其实已经停稳 | 方块原点在中心，外卖盒原点在盒底，判定是按盒底写的 | 看 `bottom_z` 时要扣掉半个物体高度（判定**未改**） |
| 37 | SSH 命令自己断开了 | `pkill -f xxx` 匹配到了执行它的那条 SSH 命令本身 | 改用 `killall` 或 `pkill -f "[x]xx"`，且命令里别再出现这个词 |
| 38 | Mac 上 rsync 报参数错误 | macOS 自带的是 openrsync，不支持 `--info=progress2` | 用 `--progress`（已修进脚本） |
| 39 | 临时目录里的脚本和下载文件丢了 | 会话的临时目录会被系统清理 | 需要保留的东西都放进项目目录 |

## 六、推流（WebRTC）

| # | 现象 | 原因 | 处理 |
| --- | --- | --- | --- |
| 40 | 客户端连上了但一直黑屏，服务器也不开 UDP 端口 | LeIsaac 的 Brev 文档用的是 `--enable omni.kit.livestream.webrtc`，IsaacLab 2.3 要用 `--livestream 1` 加环境变量 `PUBLIC_IP`（会启用 `omni.services.livestream.nvcf`） | `run_teleop.sh` 已改 |
| 41 | 信令能通，画面过不来 | 画面走 UDP 47998，用户的 VPN 只转发 TCP | 在 VPN 里给服务器 IP 加 `IP-CIDR <ip>/32 DIRECT` 规则，放在规则列表最上面 |
| 42 | 加了直连规则后，SSH 也连不上了 | 流量改走真实 IP（中国移动 <home-ip>），安全组只放行了 VPN 出口 | 安全组同时放行两个 IP；用 `myip.ipip.net` 查真实出口 IP |
| 43 | 排查时看不出客户端从哪来 | — | 临时对所有 IP 开放端口，在服务器上抓包看来源，确认后立刻收紧 |
| 44 | 客户端版本对不上 | Isaac Sim 5.1 要用 Streaming Client 1.1.5；2.x 客户端对应 Isaac Sim 6 | 下 1.1.5 |

## 七、遥操作与机械臂

| # | 现象 | 原因 | 处理 |
| --- | --- | --- | --- |
| 45 | 一按 B 机械臂就往左转，A/D 像是失灵 | LeIsaac 的键盘控制按“按下就加、松开就减”累计动作；推流客户端重复或丢失一次按键事件，“向左”就一直残留 | `patches/so101_keyboard_held_keys.patch` 改成按“当前按住的键”重算，按 B/R 清空（本地测过，**线上未复测**） |
| 46 | 外卖盒夹不住 | SO-101 是单关节旋转钳口，有效开口只有约 6–7 cm（从 USD 碰撞网格算出）；Lux3D 的盒子宽 11–12 cm | 默认用缩到 5.5 cm 的小号盒，或者换更小的实物 |
| 47 | SO-101 的 USD 里读不到网格 | 网格在实例化的子节点里 | 遍历时用 `Usd.TraverseInstanceProxies()` |

## 八、操作习惯与版本选择

| # | 现象 | 原因 | 处理 |
| --- | --- | --- | --- |
| 48 | `aws ec2 describe-instances` 找不到实例 | Mac 上 AWS CLI 的默认区域是 `us-east-2`，实例在首尔 | 每条命令带 `--region ap-northeast-2`，或先 `export AWS_REGION=ap-northeast-2` |
| 49 | 在 AWS 上装环境，下载很慢或连不上清华源 | `setup_instance.sh` 默认 `SITE=cn`，是给国内 CompShare 准备的 | 在 AWS 上一律写 `SITE=global bash ~/cogway/setup_instance.sh ...` |
| 50 | 想省事用 AWS Marketplace 上 NVIDIA 的 Isaac Sim 镜像 | 镜像名只有日期（2026-09-29），推测是 6.x；LeIsaac 只支持 Isaac Sim 4.5 / 5.0 / 5.1；订阅还要接受条款 | 不用，纯净 Ubuntu 自己装 5.1 |
| 51 | 想升级到新版 IsaacLab | IsaacLab 3.x 改成多物理后端，不支持 Isaac Sim 5.1；LeIsaac 锁定 IsaacLab 2.3.0 | 黑客松期间锁定 5.1 + 2.3.0 + LeIsaac 0.4.0 |
| 52 | 键盘录的数据拿去跑 LeIsaac 策略推理对不上 | 键盘动作是 8 维增量：前 6 维经差分 IK 只驱动 4 个关节，后 2 维（底座旋转、夹爪）直接是关节增量；策略推理要主臂录的关节角 | 训练数据用实体主臂录，键盘只用来练手和演示 |
| 53 | 停机前忘了同步，本地改的补丁不在机器上 | `stage_bundle.sh` 只在本地打补丁，要 `sync_to_instance.sh` 才会上机 | 每次开机先跑一次 `sync_to_instance.sh`，可重复执行 |

