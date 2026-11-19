# 在此目录接手续作

[README.md](README.md) 是对外的项目介绍。先读 [NOTES.md](NOTES.md)（原来的 README），其中记录了用户的原始设想、建议选题和比赛期间的进度。参赛材料和授权依据见本地的 `EVENT.md`（不进 git），技术接口、样品检查和仿真先例见 [TECHNICAL.md](TECHNICAL.md)。

实际生成资产或运行 Isaac Lab 后，把所用版本、输入、结果、失败原因和回放位置写回 NOTES.md 的进度记录，以便下一位接手者区分文档依据与实测结果。

## 当前状态（2026-11-16）

- 本仓库从 `~/Cogway/hackathon` 迁来，旧路径现在是指向这里的符号链接。GitHub：`liulhs/aholo-hackathon-team-maniforge-2026`（2026-11-19 起公开，历史已压成一个提交）。这台 Mac 的 gh 默认账号是 `jason-unika`，本仓库用本地 credential helper 固定以 `liulhs` 推送，不要改；用 `gh` 操作本仓库前先 `gh auth switch -u liulhs`，用完切回。
- 下一步主线见 [TRAINING-PLAN.md](TRAINING-PLAN.md)：从臂当遥控器，在 MuJoCo 里录示范、训练 ACT、评估成功率；LeIsaac 是保底。
- 交付物和倒排时间见本地的 `DELIVERABLES.md`；撞题分析见本地的 `COMPETITORS.md`、`PARTNER-RESOURCES.md` 和 `exports/`。这几份是内部文档，在 `.gitignore` 里，不要提交。
- 硬件（接线、上电、掰手臂）由用户动手，助手给命令、讲清楚每一步。

## 没进 git 的本地文件

- `cloud-setup/bundle/leisaac/`：LeIsaac @`24d3bcd` + IsaacLab @`3c6e67b` 子模块 + `so101_follower.usd`，约 190 MB，第三方代码。新机器上要按这两个版本重新克隆（带子模块），`stage_bundle.sh` 会检查它在不在。
- `experiments/2026-11-08-lux3d-takeout-box/**/gaussian.ply`、`result.zip`：Lux3D 原始输出，超过 GitHub 单文件 100 MB 上限，只在本机。
- `EVENT.md`、`DELIVERABLES.md`、`PARTNER-RESOURCES.md`、`COMPETITORS.md`、`exports/`：内部文档，仓库公开时留在本地。
- `experiments/2026-11-18-lux3d-objects/**/textured.glb`：Lux3D 原始输出，11 个共约 167 MB，还没决定要不要进 git。
- 仓库是公开的。文档里的 AWS 实例 ID、安全组和用户家里/VPN 的出口 IP 已换成 `<instance-id>`、`<security-group-id>`、`<home-ip>`、`<vpn-ip>`、`<public-ip>`；**不要再把真实值写进任何会提交的文件**，需要时只在本地或对话里用。

## 操作规矩

要开 GPU 机器、跑 Isaac Sim / LeIsaac 之前，先读 [cloud-setup/AWS-RUNBOOK.md](cloud-setup/AWS-RUNBOOK.md)（机器现状、重新开机步骤、还没解决的问题、操作规矩）和 [gotchas/README.md](gotchas/README.md)（踩过的坑）。`cloud-setup/README.md` 是为 CompShare 写的旧计划，以 AWS 手册为准。开机、新建、删除实例都会花钱，先问用户。
