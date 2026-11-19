# 硬件打印件

| 文件 | 是什么 | 来源 |
| --- | --- | --- |
| `WaveShare_Mounting_Plate_SO101.stl` | SO-101 官方 Waveshare 驱动板安装板 | [TheRobotStudio/SO-ARM100](https://github.com/TheRobotStudio/SO-ARM100/blob/main/STL/SO101/Individual/WaveShare_Mounting_Plate_SO101.stl)，2026-11-16 下载，未修改 |
| `mounting_plate.png` | 安装板两面的渲染图 | 由上面的 STL 渲染 |
| `board_location.png` | 驱动板装在机械臂哪里（标注图） | 官方仓库两张照片加标注 |

**尺寸（从 STL 量出）：** 外形 51 × 42 mm，底板厚 2.4 mm，一面中间有约 16–18 mm 的方形凸块，含凸块总高 7.6 mm；四角孔约 5 mm，孔距 37 × 28 mm。

**装在哪（2026-11-16 从官方照片确认）：** 底座**背面**（背对夹爪的那一面），第一个舵机下面那个方盒子的后侧，驱动板**竖着装**，接口朝外。见 `board_location.png`，证据是官方仓库的 `media/4040_base_mount.jpg`（能直接看到驱动板）和 `media/SO101_Follower.webp`（底座背面露出黄色跳线帽）。

**还没确认的：** 安装板背面的方形凸块具体卡进底座哪个孔，文档没写；底座模型里有一个约 19 mm 的方孔，可能就是它。打印出来先对一下自己的底座和驱动板铜柱再装。
