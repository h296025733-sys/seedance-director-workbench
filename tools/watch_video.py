#!/usr/bin/env python3
"""Local-first, traceable video evidence extractor.

Requires ffmpeg and ffprobe. PySceneDetect/OpenCV are used when available for
motion-tolerant shot detection. Network URLs additionally require yt-dlp and
an explicit --allow-network flag. No external transcription is implemented.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_ROOT = WORKSPACE_ROOT / "outputs"
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MODES = ("FAST", "BALANCED", "DIRECTOR", "HOOK_DENSE")
SCENE_DETECTORS = ("auto", "adaptive", "ffmpeg")


class EvidenceError(RuntimeError):
    pass


def configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def project_vendor_executable(name: str) -> str | None:
    suffix = ".exe" if os.name == "nt" else ""
    candidates = sorted(
        (WORKSPACE_ROOT / "tools" / "vendor").glob(
            f"ffmpeg-*-essentials_build/bin/{name}{suffix}"
        ),
        reverse=True,
    )
    return str(candidates[0].resolve()) if candidates else None


def windows_extended_path(path: Path, force: bool = False) -> str:
    """Return a Windows extended-length path without touching the filesystem."""
    absolute = os.path.abspath(str(path))
    if os.name != "nt" or absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute.lstrip("\\")
    return "\\\\?\\" + absolute if force or len(absolute) >= 240 else absolute


def is_within(path: Path, parent: Path) -> bool:
    try:
        child_text = os.path.abspath(str(path))
        parent_text = os.path.abspath(str(parent))
        return os.path.normcase(os.path.commonpath([child_text, parent_text])) == os.path.normcase(parent_text)
    except (ValueError, OSError):
        return False


def validate_task_name(value: str) -> str:
    name = value.strip()
    if not name or name in {".", ".."}:
        raise EvidenceError("任务名不能为空或为点路径。")
    if any(ord(char) < 32 or char in '<>:"/\\|?*' for char in name):
        raise EvidenceError("任务名包含 Windows 不允许的字符。")
    if name.endswith((" ", ".")):
        raise EvidenceError("任务名不能以空格或句点结尾。")
    if name.split(".", 1)[0].upper() in WINDOWS_RESERVED:
        raise EvidenceError("任务名是 Windows 保留设备名。")
    return name


def evidence_directory(task_name: str, override: str | None = None) -> Path:
    if override:
        target = Path(windows_extended_path(Path(override).expanduser()))
        if not is_within(target, OUTPUTS_ROOT):
            raise EvidenceError("输出目录必须位于工作区 outputs 内。")
    else:
        target = Path(windows_extended_path(OUTPUTS_ROOT / validate_task_name(task_name) / "evidence"))
    if target.exists() and any(target.iterdir()):
        raise EvidenceError(f"输出目录非空，拒绝覆盖：{target}")
    return target


def executable(name: str, env_value: str | None = None) -> str:
    if env_value:
        candidate = Path(env_value).expanduser().resolve()
        if candidate.is_file():
            return str(candidate)
        raise EvidenceError(f"{name} 指定路径不存在：{candidate}")
    found = shutil.which(name)
    if not found and name in {"ffmpeg", "ffprobe"}:
        found = project_vendor_executable(name)
    if not found:
        raise EvidenceError(f"缺少 {name}；未自动安装。请先审查并配置该依赖。")
    return found


def run(args: list[str], timeout: int = 300, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise EvidenceError(f"命令失败 ({result.returncode}): {args[0]}\n{detail[-3000:]}")
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, data: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def probe_video(ffprobe: str, source: Path) -> dict:
    result = run([
        ffprobe, "-v", "error", "-show_format", "-show_streams",
        "-of", "json", str(source.resolve())
    ])
    return json.loads(result.stdout)


def duration_from_probe(probe: dict) -> float:
    # Frame sampling must follow the video stream rather than a longer audio
    # or container tail; otherwise the requested "last frame" may not exist.
    video_durations = [
        float(stream["duration"])
        for stream in probe.get("streams", [])
        if stream.get("codec_type") == "video" and stream.get("duration") is not None
    ]
    if video_durations:
        return max(0.0, max(video_durations))
    value = probe.get("format", {}).get("duration")
    if value is not None:
        return max(0.0, float(value))
    stream_durations = [
        float(stream["duration"])
        for stream in probe.get("streams", [])
        if stream.get("duration") is not None
    ]
    return max(stream_durations, default=0.0)


def detect_scene_times_ffmpeg(ffmpeg: str, source: Path, threshold: float = 0.35) -> list[float]:
    result = run([
        ffmpeg, "-hide_banner", "-nostdin", "-i", str(source.resolve()),
        "-filter:v", f"select='gt(scene,{threshold})',showinfo",
        "-an", "-f", "null", "-"
    ], check=False)
    text = f"{result.stdout}\n{result.stderr}"
    return sorted({round(float(item), 3) for item in re.findall(r"pts_time:([0-9.]+)", text)})


def detect_scene_times_adaptive(
    source: Path,
    threshold: float = 4.0,
    min_scene_len_frames: int = 15,
) -> list[float]:
    """Use PySceneDetect's rolling-average detector to suppress motion spikes."""
    try:
        from scenedetect import AdaptiveDetector, detect
    except ImportError as exc:
        raise EvidenceError(
            "缺少 PySceneDetect/OpenCV；请使用项目 .venv 或选择 --scene-detector ffmpeg。"
        ) from exc
    try:
        scenes = detect(
            str(source.resolve()),
            AdaptiveDetector(
                adaptive_threshold=threshold,
                min_scene_len=min_scene_len_frames,
            ),
            show_progress=False,
        )
    except Exception as exc:
        raise EvidenceError(f"PySceneDetect 运行失败：{exc}") from exc
    # Each tuple is [scene_start, scene_end). The first scene starts at zero,
    # so only later starts are transition candidates.
    return sorted({round(float(scene[0].seconds), 3) for scene in scenes[1:]})


def detect_scene_times(
    ffmpeg: str,
    source: Path,
    detector: str = "auto",
    adaptive_threshold: float = 4.0,
    min_scene_len_frames: int = 15,
) -> tuple[list[float], dict]:
    if detector not in SCENE_DETECTORS:
        raise EvidenceError(f"未知镜头检测器：{detector}")
    if adaptive_threshold <= 0:
        raise EvidenceError("AdaptiveDetector 阈值必须大于 0。")
    if min_scene_len_frames < 1:
        raise EvidenceError("最短镜头帧数必须至少为 1。")
    if detector in {"auto", "adaptive"}:
        try:
            times = detect_scene_times_adaptive(
                source,
                threshold=adaptive_threshold,
                min_scene_len_frames=min_scene_len_frames,
            )
            return times, {
                "requested": detector,
                "method": "pyscenedetect_adaptive",
                "adaptive_threshold": adaptive_threshold,
                "min_scene_len_frames": min_scene_len_frames,
                "fallback": False,
            }
        except EvidenceError as exc:
            if detector == "adaptive":
                raise
            fallback_reason = str(exc)
    else:
        fallback_reason = None
    times = detect_scene_times_ffmpeg(ffmpeg, source)
    return times, {
        "requested": detector,
        "method": "ffmpeg_scene_filter",
        "ffmpeg_threshold": 0.35,
        "fallback": detector == "auto",
        "fallback_reason": fallback_reason,
    }


def uniform_times(start: float, end: float, count: int) -> list[float]:
    if count <= 1 or end <= start:
        return [max(0.0, start)]
    step = (end - start) / (count - 1)
    return [round(start + index * step, 3) for index in range(count)]


def build_shots(duration: float, scene_times: list[float]) -> list[dict]:
    boundaries = [0.0] + [time for time in scene_times if 0 < time < duration] + [duration]
    boundaries = sorted(set(round(value, 3) for value in boundaries))
    shots = []
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), 1):
        shots.append({
            "shot_id": index,
            "start": start,
            "end": end,
            "duration": round(end - start, 3),
            "detection": "scene_change" if index > 1 else "video_start",
            "confidence": "MEDIUM",
        })
    return shots


def sampling_times(mode: str, duration: float, shots: list[dict]) -> list[float]:
    if duration <= 0:
        return [0.0]
    values: list[float] = [0.0, max(0.0, duration - 0.04)]
    if mode == "FAST":
        values += uniform_times(0.0, max(0.0, duration - 0.04), min(24, max(2, math.ceil(duration))))
    elif mode == "BALANCED":
        for shot in shots:
            values += [shot["start"], (shot["start"] + shot["end"]) / 2]
    else:
        for shot in shots:
            values += [
                shot["start"],
                (shot["start"] + shot["end"]) / 2,
                max(shot["start"], shot["end"] - 0.04),
            ]
    if mode == "HOOK_DENSE":
        values += [index / 5 for index in range(0, min(5, math.floor(duration * 5)) + 1)]
        values += [1 + index / 4 for index in range(0, min(8, math.floor(max(0, duration - 1) * 4)) + 1)]
    cap = {"FAST": 24, "BALANCED": 60, "DIRECTOR": 120, "HOOK_DENSE": 140}[mode]
    valid = sorted({round(min(max(0.0, value), max(0.0, duration - 0.04)), 3) for value in values})
    if len(valid) > cap:
        indexes = uniform_times(0, len(valid) - 1, cap)
        valid = [valid[round(index)] for index in indexes]
    return sorted(set(valid))


def frame_name(timestamp: float) -> str:
    return f"t_{int(round(timestamp * 1000)):09d}.jpg"


def extract_frame(ffmpeg: str, source: Path, timestamp: float, output: Path) -> None:
    run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", f"{timestamp:.3f}", "-i", str(source.resolve()),
        "-frames:v", "1", "-q:v", "2",
        # FFmpeg 8 rejects non-full-range MJPEG under the default strictness.
        # Allow this standard frame-extraction path without changing the source.
        "-strict", "unofficial", "-y", str(output.resolve())
    ])
    if not output.is_file() or output.stat().st_size == 0:
        raise EvidenceError(f"FFmpeg 未生成有效帧：{output}")


def parse_srt(text: str) -> list[dict]:
    segments = []
    blocks = re.split(r"\r?\n\r?\n+", text.strip())
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 2:
            continue
        timing_index = 1 if lines[0].strip().isdigit() else 0
        if timing_index >= len(lines) or "-->" not in lines[timing_index]:
            continue
        start, end = [item.strip() for item in lines[timing_index].split("-->", 1)]
        segments.append({
            "start_srt": start,
            "end_srt": end,
            "text": "\n".join(lines[timing_index + 1:]).strip(),
            "source": "embedded_subtitle",
        })
    return segments


def extract_subtitles(ffmpeg: str, source: Path, output: Path, has_subtitle: bool) -> dict:
    if not has_subtitle:
        output.open("x", encoding="utf-8").close()
        return {"method": "none", "segments": [], "reason": "no embedded subtitle stream"}
    result = run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(source.resolve()), "-map", "0:s:0", "-c:s", "srt",
        "-y", str(output.resolve())
    ], check=False)
    if result.returncode != 0 or not output.exists():
        if not output.exists():
            output.open("x", encoding="utf-8").close()
        return {
            "method": "none",
            "segments": [],
            "reason": f"embedded subtitle extraction failed: {result.stderr.strip()[-1000:]}",
        }
    text = output.read_text(encoding="utf-8-sig", errors="replace")
    return {"method": "embedded_subtitle", "segments": parse_srt(text)}


def seconds_to_srt_timestamp(value: float) -> str:
    milliseconds = max(0, int(round(value * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def transcribe_local(
    source: Path,
    output: Path,
    model_dir: Path,
    device: str = "cpu",
    compute_type: str = "int8",
) -> dict:
    if not model_dir.is_dir() or not (model_dir / "model.bin").is_file():
        raise EvidenceError(f"本地 Whisper 模型不完整：{model_dir}")
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise EvidenceError("缺少 faster-whisper；请使用项目 .venv。") from exc
    try:
        model = WhisperModel(str(model_dir), device=device, compute_type=compute_type)
        generated, info = model.transcribe(
            str(source.resolve()),
            beam_size=5,
            vad_filter=True,
            word_timestamps=True,
        )
        raw_segments = list(generated)
    except Exception as exc:
        raise EvidenceError(f"本地 faster-whisper 转写失败：{exc}") from exc

    segments = []
    srt_blocks = []
    for index, segment in enumerate(raw_segments, 1):
        words = [
            {
                "start": round(float(word.start), 3) if word.start is not None else None,
                "end": round(float(word.end), 3) if word.end is not None else None,
                "text": word.word,
                "probability": round(float(word.probability), 4),
            }
            for word in (segment.words or [])
        ]
        text = segment.text.strip()
        record = {
            "start": round(float(segment.start), 3),
            "end": round(float(segment.end), 3),
            "text": text,
            "words": words,
            "source": "local_faster_whisper",
        }
        segments.append(record)
        srt_blocks.append(
            f"{index}\n{seconds_to_srt_timestamp(segment.start)} --> "
            f"{seconds_to_srt_timestamp(segment.end)}\n{text}\n"
        )
    output.write_text("\n".join(srt_blocks), encoding="utf-8", newline="\n")
    return {
        "method": "local_faster_whisper",
        "model_path": str(model_dir.resolve()),
        "device": device,
        "compute_type": compute_type,
        "language": info.language,
        "language_probability": round(float(info.language_probability), 4),
        "segments": segments,
        "review_required": True,
    }


def create_contact_sheet(frame_paths: list[Path], output: Path) -> str | None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return "Pillow unavailable"
    if not frame_paths:
        return "no frames"
    selected = frame_paths[:24]
    width, thumb_height, label_height = 320, 180, 24
    columns = 4
    rows = math.ceil(len(selected) / columns)
    sheet = Image.new("RGB", (columns * width, rows * (thumb_height + label_height)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, path in enumerate(selected):
        with Image.open(path) as image:
            image.thumbnail((width, thumb_height))
            x = (index % columns) * width + (width - image.width) // 2
            y = (index // columns) * (thumb_height + label_height)
            sheet.paste(image.convert("RGB"), (x, y))
        draw.text(((index % columns) * width + 4, y + thumb_height + 3), path.stem, fill="black")
    sheet.save(output, "JPEG", quality=90)
    return None


def obtain_source(source_value: str, allow_network: bool, yt_dlp: str | None, staging: Path) -> tuple[Path, dict]:
    parsed = urlparse(source_value)
    if parsed.scheme in {"http", "https"}:
        if not allow_network:
            raise EvidenceError("网络视频需要用户明确授权并传入 --allow-network。")
        downloader = executable("yt-dlp", yt_dlp)
        staging.mkdir(parents=True, exist_ok=False)
        template = staging / "source.%(ext)s"
        result = run([
            downloader, "--no-playlist", "--no-exec", "--restrict-filenames",
            "-o", str(template), "--", source_value
        ])
        candidates = [path for path in staging.iterdir() if path.is_file()]
        if not candidates:
            raise EvidenceError(f"yt-dlp 未产生文件：{result.stderr[-1000:]}")
        return max(candidates, key=lambda path: path.stat().st_size), {
            "kind": "authorized_network",
            "url": source_value,
        }
    source = Path(windows_extended_path(Path(source_value).expanduser()))
    if not source.is_file():
        raise EvidenceError(f"本地视频不存在：{source}")
    return source, {"kind": "local", "path": str(source)}


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--task-name", required=True)
    parser.add_argument("--mode", choices=MODES, default="BALANCED")
    parser.add_argument("--output-dir")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--external-transcription", action="store_true")
    parser.add_argument("--local-transcription", action="store_true")
    parser.add_argument("--whisper-model-dir")
    parser.add_argument("--scene-detector", choices=SCENE_DETECTORS, default="auto")
    parser.add_argument("--adaptive-threshold", type=float, default=4.0)
    parser.add_argument("--min-scene-len-frames", type=int, default=15)
    parser.add_argument("--ffmpeg")
    parser.add_argument("--ffprobe")
    parser.add_argument("--yt-dlp")
    args = parser.parse_args(argv)

    if args.external_transcription:
        raise EvidenceError("外部转录未实现且默认禁止；请单独审查服务、费用、隐私和上传授权。")

    ffmpeg = executable("ffmpeg", args.ffmpeg)
    ffprobe = executable("ffprobe", args.ffprobe)
    parsed_source = urlparse(args.source)
    if parsed_source.scheme not in {"http", "https"}:
        local_source = Path(windows_extended_path(Path(args.source).expanduser()))
        if not local_source.is_file():
            # Validate before creating the task tree so a typo does not leave
            # a misleading empty evidence directory behind.
            raise EvidenceError(f"本地视频不存在：{local_source}")
    target = evidence_directory(args.task_name, args.output_dir)
    target.mkdir(parents=True, exist_ok=False)
    for name in ("keyframes", "hook_frames", "transition_frames"):
        (target / name).mkdir()

    source, source_descriptor = obtain_source(
        args.source, args.allow_network, args.yt_dlp, target / "_network_source"
    )
    initial = {"size": source.stat().st_size, "mtime_ns": source.stat().st_mtime_ns}
    probe = probe_video(ffprobe, source)
    streams = probe.get("streams", [])
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    subtitle_streams = [stream for stream in streams if stream.get("codec_type") == "subtitle"]
    duration = duration_from_probe(probe)
    scene_times, scene_detection = detect_scene_times(
        ffmpeg,
        source,
        detector=args.scene_detector,
        adaptive_threshold=args.adaptive_threshold,
        min_scene_len_frames=args.min_scene_len_frames,
    )
    shots = build_shots(duration, scene_times)
    times = sampling_times(args.mode, duration, shots)

    frames: list[dict] = []
    for timestamp in times:
        path = target / "keyframes" / frame_name(timestamp)
        extract_frame(ffmpeg, source, timestamp, path)
        item = {"timestamp": timestamp, "path": str(path.relative_to(target)), "confidence": "HIGH"}
        frames.append(item)
        if timestamp <= 3:
            shutil.copy2(path, target / "hook_frames" / path.name)

    transition_records = []
    for timestamp in scene_times:
        for offset, label in ((-0.08, "before"), (0.08, "after")):
            sample = min(max(0.0, timestamp + offset), max(0.0, duration - 0.04))
            path = target / "transition_frames" / f"{frame_name(timestamp)[:-4]}_{label}.jpg"
            extract_frame(ffmpeg, source, sample, path)
            transition_records.append({
                "transition_time": timestamp,
                "sample_time": round(sample, 3),
                "position": label,
                "path": str(path.relative_to(target)),
            })

    transcript_path = target / "transcript.srt"
    if subtitle_streams:
        transcript = extract_subtitles(ffmpeg, source, transcript_path, True)
    elif args.local_transcription and audio_streams:
        model_dir = Path(
            windows_extended_path(
                Path(args.whisper_model_dir).expanduser()
                if args.whisper_model_dir
                else WORKSPACE_ROOT / "models" / "faster-whisper-small"
            )
        )
        transcript = transcribe_local(source, transcript_path, model_dir)
    else:
        transcript = extract_subtitles(ffmpeg, source, transcript_path, False)
        if args.local_transcription and not audio_streams:
            transcript["reason"] = "no audio stream"
    write_json(target / "transcript.json", transcript)

    for shot in shots:
        shot["keyframes"] = [
            frame["path"]
            for frame in frames
            if shot["start"] <= frame["timestamp"] <= shot["end"]
        ]
    write_json(target / "shots.json", {"shots": shots, "transitions": transition_records})
    with (target / "shots.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["shot_id", "start", "end", "duration", "detection", "confidence"])
        writer.writeheader()
        writer.writerows({key: shot[key] for key in writer.fieldnames} for shot in shots)

    audio_analysis = {
        "has_audio": bool(audio_streams),
        "method": "ffprobe_stream_metadata_only",
        "streams": [
            {
                "codec": stream.get("codec_name"),
                "channels": stream.get("channels"),
                "channel_layout": stream.get("channel_layout"),
                "sample_rate": stream.get("sample_rate"),
                "duration": stream.get("duration"),
            }
            for stream in audio_streams
        ],
        "beat_detection": {"status": "not_implemented"},
        "sound_impact_detection": {"status": "not_implemented"},
    }
    write_json(target / "audio_analysis.json", audio_analysis)

    contact_issue = create_contact_sheet(
        [target / item["path"] for item in frames], target / "contact_sheet.jpg"
    )
    final = {"size": source.stat().st_size, "mtime_ns": source.stat().st_mtime_ns}
    original_unchanged = initial == final
    metadata = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "workspace": str(WORKSPACE_ROOT),
        "source": source_descriptor,
        "processed_file": str(source),
        "source_sha256": sha256(source),
        "source_unchanged": original_unchanged,
        "mode": args.mode,
        "duration": duration,
        "format": probe.get("format"),
        "video_streams": video_streams,
        "audio_stream_count": len(audio_streams),
        "subtitle_stream_count": len(subtitle_streams),
        "frame_count": len(frames),
        "scene_change_count": len(scene_times),
        "scene_detection": scene_detection,
        "external_transcription": False,
        "local_transcription": transcript["method"] == "local_faster_whisper",
        "media_uploaded": False,
        "network_media_downloaded": source_descriptor["kind"] == "authorized_network",
    }
    write_json(target / "metadata.json", metadata)
    report = [
        "# 视频证据提取报告",
        "",
        f"- 来源：`{source_descriptor}`",
        f"- 模式：`{args.mode}`",
        f"- 时长：{duration:.3f} 秒",
        f"- 关键帧：{len(frames)}",
        f"- 场景变化：{len(scene_times)}",
        f"- 镜头检测：`{scene_detection['method']}`",
        f"- 嵌入字幕：{transcript['method']}",
        f"- 音频轨：{len(audio_streams)}",
        f"- 原文件未变：{original_unchanged}",
        f"- 本地媒体上传：否" if source_descriptor["kind"] == "local" else "- 网络素材下载：已获 --allow-network 明示",
        f"- 本地转录：{'已调用 faster-whisper；需人工校对' if transcript['method'] == 'local_faster_whisper' else '未调用'}",
        "- 外部转录：未调用；媒体未上传到转录服务",
        f"- 联系表：{'已生成' if not contact_issue else '未生成：' + contact_issue}",
        "",
        "## 限制",
        "",
        f"- 镜头切分来自 `{scene_detection['method']}`，是算法候选边界，不等于人工导演判定。",
        "- 音频仍只记录流元数据；节拍和冲击点检测尚未实现。",
        "- 嵌入字幕或本地转写都可能不完整、不准确，必须人工校对。",
    ]
    (target / "extraction_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    if not original_unchanged:
        raise EvidenceError("检测到原始文件大小或修改时间变化，结果不可接受。")
    print(json.dumps({"status": "complete", "evidence": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EvidenceError as exc:
        print(f"[watch-video] {exc}", file=sys.stderr)
        raise SystemExit(2)
