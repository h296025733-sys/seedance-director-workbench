# Seedance 视频导演工作台

这个工作台用来整理参考视频和生成方案。我的出发点是：先把动作、镜头、声音与素材职责讲清楚，再写给视频模型的提示词，减少一句笼统描述把整条片子交给模型猜的情况。

## 主要流程

```text
参考视频 → 抽帧 / 转录 / 镜头证据 → 结构拆解
        → 分镜与动作约束 → 素材职责 → 上传顺序与执行卡
```

- 本地媒体探测、关键帧与带时间戳的证据整理。
- 将视频中可见事实、推断与未知信息分别记录。
- 按参考迁移、原创、产品导演和严格复刻路由到不同技能。
- 为人物、动作、场景、镜头和素材绑定建立约束。
- 生成分镜、素材映射、官网执行卡和复核模板。
- 保留姿态参考与人脸遮挡等可选媒体辅助脚本。

`tools/` 是确定性工具，`.agents/skills/` 是技能入口，`templates/` 是交付格式，`knowledge/` 是方法说明。第三方项目源码和原始客户素材不放在此仓库。

## 本地准备

建议 Python 3.11+，自行准备 FFmpeg / ffprobe。不同辅助功能的依赖列在 `tools/requirements/`，需要用到时再安装。

```powershell
python tools/doctor.py
python tools/validate_skills.py
python tools/watch_video.py --help
python tools/build_replication_package.py --help
```

在 Codex 中可从对应 `SKILL.md` 开始，给出自己的参考片和制作需求。生成模型的模式、参数和素材限制会变化，`knowledge/` 中的记录应结合当前账号界面复核。交付执行包不等于平台已经生成成片，最终保真度需要逐镜看实际输出。

## 本次公开整理的检查

见 [检查记录](docs/verification.md)，其中区分源码与语法检查、隔离测试和未执行的真实环境路径。
