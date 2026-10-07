#!/usr/bin/env python3
"""Create identity-neutral body-pose evidence from a local video.

Run this tool with .venv-pose. It outputs a black-background stick-figure
video and JSON landmarks. Facial landmarks are intentionally omitted.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import cv2
import mediapipe as mp
import numpy as np

from watch_video import (
    EvidenceError,
    OUTPUTS_ROOT,
    configure_utf8_stdio,
    executable,
    is_within,
    probe_video,
    sha256,
    validate_task_name,
    windows_extended_path,
    write_json,
)


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
BODY_LANDMARK_START = 11
POSE_COLORS = ((0, 255, 255), (255, 80, 200), (80, 220, 80), (255, 160, 40))


def frame_rate(stream: dict) -> float:
    value = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
    numerator, denominator = value.split("/", 1)
    fps = float(numerator) / float(denominator)
    if fps <= 0:
        raise EvidenceError("无法确定有效帧率。")
    return fps


def pose_target(task_name: str, override: str | None) -> Path:
    if override:
        target = Path(windows_extended_path(Path(override).expanduser()))
        if not is_within(target, OUTPUTS_ROOT):
            raise EvidenceError("姿态输出目录必须位于工作区 outputs 内。")
    else:
        target = OUTPUTS_ROOT / validate_task_name(task_name) / "pose_reference"
    if target.exists() and any(target.iterdir()):
        raise EvidenceError(f"输出目录非空，拒绝覆盖：{target}")
    return target


def landmark_record(landmark) -> dict:
    return {
        "x": round(float(landmark.x), 6),
        "y": round(float(landmark.y), 6),
        "z": round(float(landmark.z), 6),
        "visibility": round(float(landmark.visibility), 6),
        "presence": round(float(landmark.presence), 6),
    }


def draw_body(canvas: np.ndarray, landmarks, color: tuple[int, int, int]) -> None:
    height, width = canvas.shape[:2]
    connections = mp.tasks.vision.PoseLandmarksConnections.POSE_LANDMARKS
    for connection in connections:
        if connection.start < BODY_LANDMARK_START or connection.end < BODY_LANDMARK_START:
            continue
        first, second = landmarks[connection.start], landmarks[connection.end]
        if min(first.visibility, first.presence, second.visibility, second.presence) < 0.35:
            continue
        start = (int(first.x * width), int(first.y * height))
        end = (int(second.x * width), int(second.y * height))
        cv2.line(canvas, start, end, color, 4, cv2.LINE_AA)
    for index, landmark in enumerate(landmarks):
        if index < BODY_LANDMARK_START or min(landmark.visibility, landmark.presence) < 0.35:
            continue
        point = (int(landmark.x * width), int(landmark.y * height))
        cv2.circle(canvas, point, 5, color, -1, cv2.LINE_AA)


def transform_crop_landmarks(landmarks, x0: int, crop_width: int, full_width: int):
    scale = crop_width / full_width
    return [
        SimpleNamespace(
            x=(landmark.x * crop_width + x0) / full_width,
            y=landmark.y,
            z=landmark.z * scale,
            visibility=landmark.visibility,
            presence=landmark.presence,
        )
        for landmark in landmarks
    ]


def pose_center(landmarks) -> tuple[float, float]:
    # Hips are more stable than facial points and remain identity-neutral.
    left, right = landmarks[23], landmarks[24]
    return ((left.x + right.x) / 2, (left.y + right.y) / 2)


def merge_distinct_poses(existing: list, candidates: list, limit: int) -> list:
    merged = list(existing)
    for candidate in candidates:
        candidate_center = pose_center(candidate)
        if all(
            (candidate_center[0] - pose_center(item)[0]) ** 2
            + (candidate_center[1] - pose_center(item)[1]) ** 2
            >= 0.10 ** 2
            for item in merged
        ):
            merged.append(candidate)
        if len(merged) >= limit:
            break
    return merged


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--task-name", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--model")
    parser.add_argument("--max-poses", type=int, default=2)
    parser.add_argument("--ffmpeg")
    parser.add_argument("--ffprobe")
    args = parser.parse_args(argv)

    source = Path(windows_extended_path(Path(args.source).expanduser()))
    if not source.is_file():
        raise EvidenceError(f"本地视频不存在：{source}")
    if args.max_poses < 1 or args.max_poses > 4:
        raise EvidenceError("--max-poses 必须为 1 到 4。")
    model = Path(
        windows_extended_path(
            Path(args.model).expanduser()
            if args.model
            else WORKSPACE_ROOT / "models" / "mediapipe" / "pose_landmarker_full.task"
        )
    )
    if not model.is_file():
        raise EvidenceError(f"MediaPipe 姿态模型不存在：{model}")

    ffmpeg = executable("ffmpeg", args.ffmpeg)
    ffprobe = executable("ffprobe", args.ffprobe)
    probe = probe_video(ffprobe, source)
    video_streams = [stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"]
    if not video_streams:
        raise EvidenceError("输入文件没有视频流。")
    stream = video_streams[0]
    width, height = int(stream["width"]), int(stream["height"])
    fps = frame_rate(stream)
    frame_bytes = width * height * 3
    initial = {"size": source.stat().st_size, "mtime_ns": source.stat().st_mtime_ns}

    target = pose_target(args.task_name, args.output_dir)
    target.mkdir(parents=True, exist_ok=False)
    output_video = target / "pose_reference.mp4"

    decoder = subprocess.Popen(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", str(source.resolve()), "-an", "-f", "rawvideo", "-pix_fmt", "bgr24", "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    encoder = subprocess.Popen(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}",
            "-r", f"{fps:.8f}", "-i", "-", "-an", "-c:v", "libx264",
            "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(output_video.resolve()),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    options = mp.tasks.vision.PoseLandmarkerOptions(
        # MediaPipe's native Windows layer cannot reliably open Unicode model
        # paths. Passing the already-validated local file as bytes avoids that
        # limitation without copying it outside the D-drive workspace.
        base_options=mp.tasks.BaseOptions(model_asset_buffer=model.read_bytes()),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=args.max_poses,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    crop_options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_buffer=model.read_bytes()),
        running_mode=mp.tasks.vision.RunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=0.45,
        min_pose_presence_confidence=0.45,
    )
    records = []
    frame_index = 0
    try:
        with (
            mp.tasks.vision.PoseLandmarker.create_from_options(options) as landmarker,
            mp.tasks.vision.PoseLandmarker.create_from_options(crop_options) as crop_landmarker,
        ):
            while True:
                raw = decoder.stdout.read(frame_bytes) if decoder.stdout else b""
                if not raw:
                    break
                if len(raw) != frame_bytes:
                    raise EvidenceError("FFmpeg 解码返回了不完整视频帧。")
                frame = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3))
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                timestamp_ms = int(round(frame_index * 1000 / fps))
                result = landmarker.detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb),
                    timestamp_ms,
                )
                poses = list(result.pose_landmarks)
                if args.max_poses > 1 and len(poses) < args.max_poses:
                    crop_candidates = []
                    for x0, x1 in ((0, int(width * 0.62)), (int(width * 0.38), width)):
                        crop = np.ascontiguousarray(rgb[:, x0:x1])
                        crop_result = crop_landmarker.detect(
                            mp.Image(image_format=mp.ImageFormat.SRGB, data=crop)
                        )
                        if crop_result.pose_landmarks:
                            crop_candidates.append(
                                transform_crop_landmarks(
                                    crop_result.pose_landmarks[0], x0, x1 - x0, width
                                )
                            )
                    poses = merge_distinct_poses(poses, crop_candidates, args.max_poses)
                canvas = np.zeros_like(frame)
                for pose_index, landmarks in enumerate(poses):
                    draw_body(canvas, landmarks, POSE_COLORS[pose_index % len(POSE_COLORS)])
                records.append({
                    "frame": frame_index,
                    "timestamp_ms": timestamp_ms,
                    "poses": [
                        [landmark_record(landmark) for landmark in landmarks]
                        for landmarks in poses
                    ],
                })
                if not encoder.stdin:
                    raise EvidenceError("FFmpeg 编码管道不可用。")
                encoder.stdin.write(canvas.tobytes())
                frame_index += 1
    finally:
        if decoder.stdout:
            decoder.stdout.close()
        if encoder.stdin:
            encoder.stdin.close()

    decoder_stderr = decoder.stderr.read().decode("utf-8", "replace") if decoder.stderr else ""
    encoder_stderr = encoder.stderr.read().decode("utf-8", "replace") if encoder.stderr else ""
    decoder_code = decoder.wait()
    encoder_code = encoder.wait()
    if decoder_code != 0:
        raise EvidenceError(f"FFmpeg 解码失败：{decoder_stderr[-2000:]}")
    if encoder_code != 0 or not output_video.is_file():
        raise EvidenceError(f"FFmpeg 姿态视频编码失败：{encoder_stderr[-2000:]}")

    final = {"size": source.stat().st_size, "mtime_ns": source.stat().st_mtime_ns}
    metadata = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "source_sha256": sha256(source),
        "source_unchanged": initial == final,
        "model": str(model),
        "model_sha256": sha256(model),
        "width": width,
        "height": height,
        "fps": fps,
        "frames": frame_index,
        "max_poses": args.max_poses,
        "detection_strategy": "full_frame_video_plus_overlapping_left_right_image_fallback",
        "facial_landmarks_rendered": False,
        "media_uploaded": False,
        "usage_status": "internal_motion_evidence_pending_seedance_acceptance_test",
    }
    write_json(target / "pose_landmarks.json", {"metadata": metadata, "frames": records})
    write_json(target / "metadata.json", metadata)
    if initial != final:
        raise EvidenceError("检测到原始文件大小或修改时间变化，结果不可接受。")
    print(json.dumps({"status": "complete", "output": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EvidenceError as exc:
        print(f"[pose-reference] {exc}", file=sys.stderr)
        raise SystemExit(2)
