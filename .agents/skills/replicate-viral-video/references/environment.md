# 环境体检与安装说明（Windows）

## 目标

新 Codex 不应先重装。先执行 Skill 自带的只读体检，再按缺口安装。大型依赖、模型和缓存放在 D 盘；个人 Skill 本身很小，可以位于 `%USERPROFILE%\.codex\skills\replicate-viral-video` 以便所有新任务发现。

默认工作台：

`D:\workspace\Seedance视频导演工作台`

## 启动体检

在 PowerShell 中运行：

```powershell
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.codex\skills\replicate-viral-video\scripts\doctor.ps1" -WorkbenchRoot "D:\workspace\Seedance视频导演工作台"
```

体检是只读的，检查：

- 工作台及 `AGENTS.md`、知识库、模板、工具是否存在。
- Python 核心环境 `.venv` 和姿态/人脸环境 `.venv-pose`。
- FFmpeg 与 FFprobe（PATH 或工作台 `tools/vendor`）。
- 核心包和姿态包是否可导入。
- BlazeFace、YuNet、Pose Landmarker 模型是否存在。
- 当前 Skill 的关键文件是否齐全。
- D 盘可用空间。

退出码：0 表示复刻工作流的最低本地依赖齐备；2 表示缺项；3 表示脚本自身错误。它不检查即梦账号、上传审核或付费生成。

## 当前同机已验证环境（2026-08-03）

工作台已经包含：

- Python 3.12.13 项目隔离环境。
- FFmpeg/FFprobe 8.1.2 的 D 盘本地副本。
- `scenedetect-headless 0.7.1`。
- `opencv-python-headless 4.12.0.88`。
- `faster-whisper 1.2.1`。
- `yt-dlp 2026.7.4`。
- `PyYAML 6.0.3`、`Pillow 12.3.0`、`numpy 2.2.6`。
- 独立 `.venv-pose`：`mediapipe 0.10.35`、`opencv-contrib-python 4.12.0.88`、`numpy 2.2.6`。
- BlazeFace Short Range、YuNet 2023mar、Pose Landmarker Full 本地模型。

这些版本在当前机器有本地执行证据，但仍需以体检结果为准。不要因为文档写着“已安装”就跳过检查。

## 缺项安装策略

仅在工作区规则/用户授权允许后执行安装。此用户已表达的长期偏好是：免费、安全、依赖和缓存不占 C 盘；任何新第三方项目先审查，垃圾依赖不装。新 Codex仍需遵守当前任务中的权限规则。

### Python 环境

优先使用工作台已有锁文件：

- `tools/requirements/core.lock.txt`
- `tools/requirements/pose.lock.txt`
- `tools/requirements/audit.lock.txt`

若锁文件不存在，使用 Skill 的最小依赖清单作为恢复基线，不要声称与原环境完全等价。核心与 MediaPipe 必须分开，因为 `opencv-python-headless` 与 `opencv-contrib-python` 不应混装。

```powershell
$root = 'D:\workspace\Seedance视频导演工作台'
python -m venv "$root\.venv"
& "$root\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$root\.venv\Scripts\python.exe" -m pip install -r "$env:USERPROFILE\.codex\skills\replicate-viral-video\scripts\requirements-core.txt"

python -m venv "$root\.venv-pose"
& "$root\.venv-pose\Scripts\python.exe" -m pip install --upgrade pip
& "$root\.venv-pose\Scripts\python.exe" -m pip install -r "$env:USERPROFILE\.codex\skills\replicate-viral-video\scripts\requirements-pose.txt"
```

如果系统 `python` 不可用，先使用 Codex 工作区依赖定位工具查找捆绑 Python，或请用户确认一个可信 Python 3.12 安装来源。不要把 venv 创建在 C 盘临时目录。

### FFmpeg

优先顺序：

1. 工作台 `tools/vendor/ffmpeg-*-essentials_build/bin/ffmpeg.exe`。
2. 已在 PATH 的可信 FFmpeg/FFprobe。
3. 从 FFmpeg 官方下载页列出的 Windows 构建来源获取，保存到 D 盘，核对发布方/哈希后解压。

不要静默运行远程 PowerShell 管道脚本，不修改系统 PATH。通过脚本参数或工作台自动发现使用本地可执行文件。

### 人脸模型

可信来源：

- BlazeFace Short Range：Google MediaPipe 官方模型存储。
- YuNet 2023mar：OpenCV 官方 Model Zoo。
- Pose Landmarker Full：Google MediaPipe 官方模型存储。

下载前记录 URL、访问日期、大小和 SHA-256，保存到 `D:\workspace\Seedance视频导演工作台\models`。不要用不明镜像或把模型放到 C 盘缓存。当前已验证哈希：

- BlazeFace：`b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f`
- YuNet：`8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`
- Pose Landmarker Full：`4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad`

下载资源可能更新；哈希不匹配时停止，先核对官方版本，不要强行继续。

## 工具路由

- 视频取证：核心环境运行 `tools/watch_video.py`。
- 本地转写：核心环境运行 faster-whisper；输出是辅助证据，需要人工校对。
- 去身份动作参考：姿态环境运行 `tools/anonymize_face_reference.py`。
- 姿态图：只作内部诊断，默认不上传。
- 环境审计：使用 `.venv-audit` 和工作台审计锁文件；“无已知漏洞”只代表扫描时公开数据库未命中。

## 能力缺口处理

遇到新问题时先尝试 FFmpeg、现有 Python 库和轻量脚本。确需第三方项目时：查官方/成熟项目，检查维护历史、许可证、发布、代码与文档一致性、供应链风险、权限、遥测和回滚；优先 A/B 级，D/E 级不装。把审查写入工作区知识库后再安装。

## 迁移到另一台电脑

至少复制两部分：

1. 本 Skill 文件夹到新机 `%USERPROFILE%\.codex\skills\replicate-viral-video`。
2. `D:\workspace\Seedance视频导演工作台` 的知识库、工具、requirements、models；venv 和 FFmpeg 可重新创建/下载，避免直接搬运不可移植的虚拟环境。

新 Codex 第一句可用：

`使用 $replicate-viral-video，先运行只读环境体检并读取 D:\workspace\Seedance视频导演工作台 的长期经验，然后再处理我给的视频。缺失的免费安全依赖只装到 D 盘；付费生成前必须完成双重审核。`

## 回滚

- 删除个人 Skill 文件夹只会移除自动发现入口，不会删工作台数据。
- 删除某个 D 盘 venv 前先确认没有进程占用；模型、输出和原始视频分开处理。
- 不删除 `outputs/` 或用户原始素材。依赖回滚用锁文件重建，不用系统级卸载。
