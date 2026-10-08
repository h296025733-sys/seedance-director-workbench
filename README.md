# Seedance 视频导演工作台

**把参考片拆成时间轴证据、分镜约束和素材执行包。**

“照这个拍”容易遗漏动作、镜头与声音之间的关系。这个工具集先整理参考片中能看到和听到的内容，再描述哪些结构要保留、哪些元素要替换，最后形成给模型平台执行的材料。

## 一份参考片，最后交付什么

| 阶段 | 留下的内容 |
| --- | --- |
| 取证 | 媒体信息、关键帧、转录与时间戳；可见事实、推断和未知分开记。 |
| 拆解 | 动作、机位、运镜、节奏与声音关系；决定参考迁移、原创或严格复刻路径。 |
| 约束 | 人物、产品、场景与动作的职责，参考素材的绑定关系。 |
| 执行包 | 分镜、素材映射、上传顺序、平台执行卡与生成后复核模板。 |

确定性工具在 [tools/](tools/)，复刻技能在 [skills/replicate-viral-video/](skills/replicate-viral-video/)，产品导演技能在 [skills/viral-product-director/](skills/viral-product-director/)。[执行包构建器](tools/build_replication_package.py) 和 [回归用例](tests/test_replication_package.py) 可以一起阅读。

素材职责与平台模式单独存为知识表，方便在平台条件变化时复核。姿态参考、人脸遮挡等辅助脚本按需使用，第三方项目源码和客户原片不包含在仓库里。

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
