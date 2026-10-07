#!/usr/bin/env python3
"""Create a motion-reference video with every detected face fully occluded.

The output keeps the original frame timing and audio. It is intended as a
privacy-preserving motion reference, not as an identity reference.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np


@dataclass
class Track:
    boxes: dict[int, tuple[float, float, float, float]] = field(default_factory=dict)
    last_frame: int = -1
    last_box: tuple[float, float, float, float] | None = None


def center(box: tuple[float, float, float, float]) -> tuple[float, float]:
    x, y, w, h = box
    return x + w / 2.0, y + h / 2.0


def match_cost(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax, ay = center(a)
    bx, by = center(b)
    scale = max(a[2], a[3], b[2], b[3], 1.0)
    distance = math.hypot(ax - bx, ay - by) / scale
    size_change = abs(math.log(max(b[2] * b[3], 1.0) / max(a[2] * a[3], 1.0)))
    return distance + 0.25 * size_change


def detect_all_frames(
    input_path: Path,
    model_path: Path,
    yunet_path: Path,
    min_confidence: float,
) -> tuple[list[list[tuple[float, float, float, float]]], dict]:
    cap = cv2.VideoCapture(str(input_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open input video: {input_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    # YuNet complements BlazeFace on strong side profiles. Its high threshold
    # avoids the many hand/background false positives seen at permissive values.
    yunet = cv2.FaceDetectorYN.create(
        str(yunet_path), "", (width, height),
        score_threshold=max(0.85, min_confidence), nms_threshold=0.30, top_k=5000,
    )
    yunet_small = cv2.FaceDetectorYN.create(
        str(yunet_path), "", (width, height),
        score_threshold=0.65, nms_threshold=0.30, top_k=5000,
    )

    base_options = mp.tasks.BaseOptions(model_asset_path=str(model_path))
    options = mp.tasks.vision.FaceDetectorOptions(
        base_options=base_options,
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        min_detection_confidence=min_confidence,
        min_suppression_threshold=0.30,
    )
    all_boxes: list[list[tuple[float, float, float, float]]] = []
    with mp.tasks.vision.FaceDetector.create_from_options(options) as detector:
        index = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            timestamp_ms = int(round(index * 1000.0 / fps))
            result = detector.detect_for_video(image, timestamp_ms)
            boxes = []
            for detection in result.detections:
                bbox = detection.bounding_box
                x = max(0.0, float(bbox.origin_x))
                y = max(0.0, float(bbox.origin_y))
                w = min(float(width) - x, float(bbox.width))
                h = min(float(height) - y, float(bbox.height))
                if w >= 8 and h >= 8:
                    boxes.append((x, y, w, h))
            mp_boxes = deduplicate_boxes(boxes)
            boxes = list(mp_boxes)
            _, yunet_faces = yunet.detect(frame)
            if yunet_faces is not None:
                for face in yunet_faces:
                    x, y, w, h = [float(v) for v in face[:4]]
                    x = max(0.0, x)
                    y = max(0.0, y)
                    w = min(float(width) - x, w)
                    h = min(float(height) - y, h)
                    candidate = (x, y, w, h)
                    # Add YuNet only when it finds a distinct face that the
                    # primary detector did not already cover. This keeps side
                    # profile recovery without doubling every frontal mask.
                    ccx, ccy = center(candidate)
                    already_covered = False
                    for primary in mp_boxes:
                        pcx, pcy = center(primary)
                        distance = math.hypot(ccx - pcx, ccy - pcy)
                        scale = max(candidate[2], candidate[3], primary[2], primary[3], 1.0)
                        if box_iou(candidate, primary) >= 0.10 or distance <= 0.62 * scale:
                            already_covered = True
                            break
                    if w >= 8 and h >= 8 and not already_covered:
                        boxes.append(candidate)
            # A separate permissive pass is restricted to genuinely small
            # boxes. It catches distant background faces without allowing
            # hand/chair false positives to create large action-blocking masks.
            _, small_faces = yunet_small.detect(frame)
            if small_faces is not None:
                for face in small_faces:
                    x, y, w, h = [float(v) for v in face[:4]]
                    x = max(0.0, x)
                    y = max(0.0, y)
                    w = min(float(width) - x, w)
                    h = min(float(height) - y, h)
                    candidate = (x, y, w, h)
                    if w < 8 or h < 8 or max(w, h) > 90:
                        continue
                    ccx, ccy = center(candidate)
                    already_covered = False
                    for existing in boxes:
                        ecx, ecy = center(existing)
                        distance = math.hypot(ccx - ecx, ccy - ecy)
                        scale = max(candidate[2], candidate[3], existing[2], existing[3], 1.0)
                        if box_iou(candidate, existing) >= 0.10 or distance <= 0.62 * scale:
                            already_covered = True
                            break
                    if not already_covered:
                        boxes.append(candidate)
            # In this upper-body reference workflow, a very large detection
            # centered deep in the lower frame is a known chair/clothing false
            # positive. Keep small background faces, discard only implausibly
            # large lower-frame boxes.
            filtered = []
            for box in boxes:
                _, cy = center(box)
                too_large_low = (
                    cy > 0.64 * height
                    and (box[2] > 0.30 * width or box[3] > 0.22 * height)
                )
                if not too_large_low:
                    filtered.append(box)
            boxes = deduplicate_boxes(filtered)
            all_boxes.append(boxes)
            index += 1
    cap.release()
    meta = {"fps": fps, "width": width, "height": height, "frames": len(all_boxes)}
    return all_boxes, meta


def box_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = aw * ah + bw * bh - intersection
    return intersection / max(union, 1.0)


def deduplicate_boxes(
    boxes: list[tuple[float, float, float, float]],
) -> list[tuple[float, float, float, float]]:
    kept: list[tuple[float, float, float, float]] = []
    for candidate in sorted(boxes, key=lambda box: box[2] * box[3], reverse=True):
        if any(box_iou(candidate, existing) >= 0.18 for existing in kept):
            continue
        kept.append(candidate)
    return kept


def build_tracks(
    detections: list[list[tuple[float, float, float, float]]],
    max_association_gap: int = 12,
    max_cost: float = 2.2,
) -> list[Track]:
    tracks: list[Track] = []
    active: list[int] = []
    for frame_index, boxes in enumerate(detections):
        active = [tid for tid in active if frame_index - tracks[tid].last_frame <= max_association_gap]
        pairs: list[tuple[float, int, int]] = []
        for tid in active:
            previous = tracks[tid].last_box
            assert previous is not None
            for bid, box in enumerate(boxes):
                pairs.append((match_cost(previous, box), tid, bid))
        pairs.sort()
        used_tracks: set[int] = set()
        used_boxes: set[int] = set()
        for cost, tid, bid in pairs:
            if cost > max_cost or tid in used_tracks or bid in used_boxes:
                continue
            track = tracks[tid]
            track.boxes[frame_index] = boxes[bid]
            track.last_frame = frame_index
            track.last_box = boxes[bid]
            used_tracks.add(tid)
            used_boxes.add(bid)
        for bid, box in enumerate(boxes):
            if bid in used_boxes:
                continue
            track = Track(boxes={frame_index: box}, last_frame=frame_index, last_box=box)
            tracks.append(track)
            active.append(len(tracks) - 1)
        for tid in used_tracks:
            if tid not in active:
                active.append(tid)
    return tracks


def interpolate_track(
    track: Track,
    frame_count: int,
    max_internal_gap: int = 60,
    edge_extension: int = 24,
) -> dict[int, tuple[float, float, float, float]]:
    if not track.boxes:
        return {}
    keys = sorted(track.boxes)
    filled = dict(track.boxes)
    for left, right in zip(keys, keys[1:]):
        gap = right - left
        if gap <= 1 or gap > max_internal_gap:
            continue
        a = np.asarray(track.boxes[left], dtype=np.float32)
        b = np.asarray(track.boxes[right], dtype=np.float32)
        for frame_index in range(left + 1, right):
            alpha = (frame_index - left) / gap
            filled[frame_index] = tuple((a * (1.0 - alpha) + b * alpha).tolist())
    first, last = keys[0], keys[-1]
    for frame_index in range(max(0, first - edge_extension), first):
        filled[frame_index] = track.boxes[first]
    for frame_index in range(last + 1, min(frame_count, last + edge_extension + 1)):
        filled[frame_index] = track.boxes[last]
    return filled


def expanded_box(
    box: tuple[float, float, float, float],
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    x, y, w, h = box
    cx = x + w / 2.0
    cy = y + h / 2.0 + 0.03 * h
    # Tight facial oval for foreground actors; tiny distant faces get a wider
    # margin because compression can otherwise leave recognizable edge pixels.
    if max(w, h) <= 90:
        out_w = 1.80 * w
        out_h = 2.00 * h
    else:
        out_w = 1.24 * w
        out_h = 1.38 * h
    x1 = max(0, int(round(cx - out_w / 2.0)))
    y1 = max(0, int(round(cy - out_h / 2.0)))
    x2 = min(width - 1, int(round(cx + out_w / 2.0)))
    y2 = min(height - 1, int(round(cy + out_h / 2.0)))
    return x1, y1, x2, y2


def render_mask(frame: np.ndarray, boxes: list[tuple[float, float, float, float]]) -> None:
    height, width = frame.shape[:2]
    for box in boxes:
        x1, y1, x2, y2 = expanded_box(box, width, height)
        # A featureless oval destroys facial landmarks while keeping nearby
        # hands and upper-body motion substantially more readable than a box.
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        axes = (max(1, (x2 - x1) // 2), max(1, (y2 - y1) // 2))
        cv2.ellipse(frame, (cx, cy), axes, 0, 0, 360, (18, 18, 18), thickness=-1,
                    lineType=cv2.LINE_AA)


def mask_coverage_stats(
    masks_by_frame: list[list[tuple[float, float, float, float]]],
    width: int,
    height: int,
) -> dict[str, float]:
    ratios = []
    for boxes in masks_by_frame:
        canvas = np.zeros((height, width), dtype=np.uint8)
        for box in boxes:
            x1, y1, x2, y2 = expanded_box(box, width, height)
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            axes = (max(1, (x2 - x1) // 2), max(1, (y2 - y1) // 2))
            cv2.ellipse(canvas, (cx, cy), axes, 0, 0, 360, 255, thickness=-1)
        ratios.append(float(np.count_nonzero(canvas)) / float(width * height))
    return {
        "mean_percent": round(float(np.mean(ratios)) * 100.0, 3),
        "p95_percent": round(float(np.percentile(ratios, 95)) * 100.0, 3),
        "max_percent": round(float(np.max(ratios)) * 100.0, 3),
    }


def run_ffmpeg(command: list[str]) -> None:
    process = subprocess.run(command, capture_output=True, text=True)
    if process.returncode != 0:
        raise RuntimeError("FFmpeg failed:\n" + process.stderr[-4000:])


def encode_video(
    input_path: Path,
    output_path: Path,
    ffmpeg_path: Path,
    masks_by_frame: list[list[tuple[float, float, float, float]]],
    meta: dict,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="face-mask-", dir=str(output_path.parent)) as temp_dir:
        video_only = Path(temp_dir) / "video-only.mp4"
        command = [
            str(ffmpeg_path), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{meta['width']}x{meta['height']}",
            "-r", f"{meta['fps']:.8f}", "-i", "-",
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video_only),
        ]
        encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        assert encoder.stdin is not None
        cap = cv2.VideoCapture(str(input_path))
        frame_index = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            render_mask(frame, masks_by_frame[frame_index])
            encoder.stdin.write(frame.tobytes())
            frame_index += 1
        cap.release()
        encoder.stdin.close()
        stderr = encoder.stderr.read().decode("utf-8", errors="replace") if encoder.stderr else ""
        return_code = encoder.wait()
        if return_code != 0:
            raise RuntimeError("FFmpeg video encoding failed:\n" + stderr[-4000:])

        # Copy the newly encoded video and preserve source audio when present.
        run_ffmpeg([
            str(ffmpeg_path), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(video_only), "-i", str(input_path),
            "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart",
            str(output_path),
        ])


def contact_sheet(video_path: Path, output_path: Path, columns: int = 4, rows: int = 4) -> None:
    cap = cv2.VideoCapture(str(video_path))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    samples = np.linspace(0, max(frame_count - 1, 0), columns * rows, dtype=int)
    thumbs = []
    thumb_w, thumb_h = 288, 512
    for frame_index in samples:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
        ok, frame = cap.read()
        if not ok:
            continue
        frame = cv2.resize(frame, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)
        cv2.putText(frame, f"{frame_index / fps:.2f}s", (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (255, 255, 255), 2, cv2.LINE_AA)
        thumbs.append(frame)
    cap.release()
    if len(thumbs) != columns * rows:
        raise RuntimeError(f"Contact sheet sampling failed: {len(thumbs)} frames")
    sheet = np.vstack([np.hstack(thumbs[r * columns:(r + 1) * columns]) for r in range(rows)])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower() or ".jpg"
    ok, encoded = cv2.imencode(suffix, sheet, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError(f"Cannot encode contact sheet: {output_path}")
    encoded.tofile(str(output_path))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--yunet", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--contact-sheet", type=Path, required=True)
    parser.add_argument("--min-confidence", type=float, default=0.20)
    args = parser.parse_args()

    detections, meta = detect_all_frames(args.input, args.model, args.yunet, args.min_confidence)
    tracks = build_tracks(detections)
    tracks = [
        track for track in tracks
        if len(track.boxes) >= 3
        or (track.last_box is not None and max(track.last_box[2], track.last_box[3]) <= 90)
    ]
    interpolated = [interpolate_track(track, meta["frames"], max_internal_gap=30, edge_extension=6)
                    for track in tracks]
    masks_by_frame: list[list[tuple[float, float, float, float]]] = []
    for frame_index in range(meta["frames"]):
        frame_boxes = [track[frame_index] for track in interpolated if frame_index in track]
        masks_by_frame.append(deduplicate_boxes(frame_boxes))

    uncovered = [i for i, boxes in enumerate(masks_by_frame) if not boxes]
    encode_video(args.input, args.output, args.ffmpeg, masks_by_frame, meta)
    contact_sheet(args.output, args.contact_sheet)

    # A second detector pass is an automated leak check, not a platform acceptance guarantee.
    remaining, output_meta = detect_all_frames(args.output, args.model, args.yunet, 0.70)
    remaining_frames = [i for i, boxes in enumerate(remaining) if boxes]
    report = {
        "input": str(args.input.resolve()),
        "output": str(args.output.resolve()),
        "metadata": meta,
        "source_detection_frames": sum(bool(x) for x in detections),
        "source_detection_count": sum(len(x) for x in detections),
        "tracks": len(tracks),
        "masked_frames": sum(bool(x) for x in masks_by_frame),
        "mask_coverage": mask_coverage_stats(masks_by_frame, meta["width"], meta["height"]),
        "frames_without_mask": uncovered,
        "post_mask_detector_frames": remaining_frames,
        "post_mask_detector_count": sum(len(x) for x in remaining),
        "output_metadata": output_meta,
        "note": "Detector leak check passed only when post_mask_detector_count is zero; platform moderation remains external.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not remaining_frames else 2


if __name__ == "__main__":
    raise SystemExit(main())
