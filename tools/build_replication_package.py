#!/usr/bin/env python3
"""Build a traceable high-fidelity structure-transfer package from video evidence.

The package separates what must be preserved, replaced, varied, and explicitly
ignored. It creates deterministic prompts and image briefs, but it does not
generate images, upload media, operate Seedance, or guarantee replication.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_ROOT = WORKSPACE_ROOT / "outputs"
STRATEGIES = ("character-swap", "camera-variation", "style-variation", "hybrid")


def configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


class PackageError(RuntimeError):
    pass


@dataclass(frozen=True)
class PackageRequest:
    evidence_dir: Path
    strategy: str
    target_subject: str | None = None
    camera_change: str | None = None
    style_target: str | None = None
    product: str | None = None
    goal: str = "高保真迁移参考视频结构"
    rights_status: str = "unknown"
    identity_consent: str = "unknown"
    output_dir: Path | None = None


def is_within(path: Path, parent: Path) -> bool:
    try:
        child = os.path.abspath(str(path))
        root = os.path.abspath(str(parent))
        return os.path.normcase(os.path.commonpath([child, root])) == os.path.normcase(root)
    except (OSError, ValueError):
        return False


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PackageError(f"缺少证据文件：{path}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"证据 JSON 无法读取：{path}: {exc}") from exc


def write_text(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text.rstrip() + "\n")


def write_json(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def validate_request(request: PackageRequest) -> None:
    if request.strategy not in STRATEGIES:
        raise PackageError(f"未知迁移策略：{request.strategy}")
    if not is_within(request.evidence_dir, OUTPUTS_ROOT):
        raise PackageError("证据目录必须位于工作区 outputs 内。")
    if request.strategy in {"character-swap", "hybrid"} and not request.target_subject:
        raise PackageError("人物替换或混合模式必须提供 --target-subject。")
    if request.strategy == "camera-variation" and not request.camera_change:
        raise PackageError("镜头变化模式必须提供 --camera-change。")
    if request.strategy == "style-variation" and not request.style_target:
        raise PackageError("风格变化模式必须提供 --style-target。")
    if request.rights_status not in {"confirmed", "unknown"}:
        raise PackageError("rights_status 只能是 confirmed 或 unknown。")
    if request.identity_consent not in {"confirmed", "not-applicable", "unknown"}:
        raise PackageError("identity_consent 状态无效。")


def load_evidence(evidence_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metadata = read_json(evidence_dir / "metadata.json")
    shot_payload = read_json(evidence_dir / "shots.json")
    shots = shot_payload.get("shots")
    if not isinstance(metadata, dict) or not isinstance(shots, list) or not shots:
        raise PackageError("证据包缺少有效 metadata 或 shots。")
    required = {"shot_id", "start", "end", "duration"}
    for shot in shots:
        if not isinstance(shot, dict) or not required.issubset(shot):
            raise PackageError("shots.json 存在字段不完整的镜头。")
    return metadata, shots


def output_directory(request: PackageRequest) -> Path:
    target = request.output_dir or request.evidence_dir.parent / "replication_package"
    target = target.expanduser().resolve()
    if not is_within(target, OUTPUTS_ROOT):
        raise PackageError("迁移包输出目录必须位于 outputs 内。")
    if target.exists() and any(target.iterdir()):
        raise PackageError(f"输出目录非空，拒绝覆盖：{target}")
    return target


def source_dimensions(metadata: dict[str, Any]) -> tuple[int | None, int | None]:
    streams = metadata.get("video_streams") or []
    if streams and isinstance(streams[0], dict):
        return streams[0].get("width"), streams[0].get("height")
    return None, None


def nearest_ratio(width: int | None, height: int | None) -> str:
    if not width or not height:
        return "保持原片比例（需从当前官网确认可选项）"
    candidates = {
        "9:16": 9 / 16,
        "3:4": 3 / 4,
        "1:1": 1.0,
        "4:3": 4 / 3,
        "16:9": 16 / 9,
        "21:9": 21 / 9,
    }
    value = width / height
    label = min(candidates, key=lambda item: abs(candidates[item] - value))
    return f"{label}（根据原片 {width}×{height} 推算；仍需官网确认）"


def duration_plan(duration: float) -> dict[str, Any]:
    if duration <= 0:
        return {
            "source_seconds": duration,
            "recommended": "UNKNOWN",
            "segments": [],
            "reason": "源时长不可用。",
        }
    segment_count = max(1, math.ceil(duration / 15.0))
    segments = []
    for index in range(segment_count):
        start = index * 15.0
        end = min(duration, (index + 1) * 15.0)
        generation_seconds = min(15, max(4, math.ceil(end - start)))
        segments.append({
            "segment": index + 1,
            "source_start": round(start, 3),
            "source_end": round(end, 3),
            "website_duration_candidate": generation_seconds,
        })
    return {
        "source_seconds": round(duration, 3),
        "recommended": (
            f"{segments[0]['website_duration_candidate']} 秒单段候选"
            if segment_count == 1
            else f"拆为 {segment_count} 段，每段不超过 15 秒"
        ),
        "segments": segments,
        "reason": "公开模型资料支持 4–15 秒；当前账号选项仍需确认。",
    }


def strategy_rules(request: PackageRequest) -> dict[str, list[str]]:
    hard_locks = [
        "镜头数量与镜头顺序",
        "每个镜头的起止时间和节奏功能",
        "关键动作发生时刻与剪辑点",
        "首帧信息功能和结尾落点",
    ]
    soft_locks = ["主体在画面中的相对位置", "光线方向", "情绪曲线", "声音冲击点"]
    replace = ["原人物身份、面部、体型特征、发型和服装", "原品牌、Logo、字幕和专属文案"]
    vary: list[str] = []
    if request.strategy in {"camera-variation", "hybrid"} and request.camera_change:
        vary.append(f"镜头视角变化：{request.camera_change}")
        soft_locks.append("原运镜仅作为节奏参考，不锁死机位")
    else:
        hard_locks.append("景别、机位、构图和运镜轨迹")
    if request.strategy in {"style-variation", "hybrid"} and request.style_target:
        vary.append(f"目标视觉风格：{request.style_target}")
    else:
        soft_locks.extend(["色彩关系", "材质与光影气质"])
    if request.target_subject:
        replace.append(f"目标人物：{request.target_subject}")
    if request.product:
        replace.append(f"目标产品/道具：{request.product}")
    do_not_reference = [
        "原人物可识别身份",
        "原品牌与商标",
        "原字幕、口播文案和水印",
        "未经授权的独特角色设定或受保护视觉表达",
    ]
    return {
        "hard_locks": hard_locks,
        "soft_locks": soft_locks,
        "replace": replace,
        "vary": vary,
        "do_not_reference": do_not_reference,
    }


def representative_frame(shot: dict[str, Any]) -> str | None:
    frames = shot.get("keyframes") or []
    if not frames:
        return None
    return str(frames[len(frames) // 2])


def create_structure_storyboard(
    evidence_dir: Path,
    shots: list[dict[str, Any]],
    output_path: Path,
) -> dict[str, Any]:
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageOps
    except ImportError:
        return {"status": "not_generated", "reason": "Pillow unavailable"}

    selected: list[tuple[dict[str, Any], Path, str]] = []
    for shot in shots[:12]:
        relatives = [str(item) for item in (shot.get("keyframes") or [])]
        if not relatives:
            continue
        if len(shots) <= 3:
            indexes = sorted({0, len(relatives) // 2, len(relatives) - 1})
        else:
            indexes = [len(relatives) // 2]
        for position, index in enumerate(indexes):
            frame = evidence_dir / relatives[index]
            if frame.is_file():
                selected.append((shot, frame, chr(ord("A") + position)))
                if len(selected) >= 12:
                    break
        if len(selected) >= 12:
            break
    if not selected:
        return {"status": "not_generated", "reason": "no referenced keyframes found"}

    columns, cell_width, image_height, label_height = min(3, len(selected)), 360, 203, 30
    rows = math.ceil(len(selected) / columns)
    sheet = Image.new("RGB", (columns * cell_width, rows * (image_height + label_height)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (shot, path, position) in enumerate(selected):
        with Image.open(path) as original:
            gray = ImageOps.grayscale(original)
            gray.thumbnail((cell_width, image_height))
            masses = gray.filter(ImageFilter.GaussianBlur(8))
            masses = ImageOps.posterize(masses.convert("RGB"), 3).convert("L")
            edges = gray.filter(ImageFilter.GaussianBlur(2)).filter(ImageFilter.FIND_EDGES)
            edges = ImageOps.invert(ImageOps.autocontrast(edges))
            structure = Image.blend(masses, edges, 0.35)
            structure = ImageOps.autocontrast(structure, cutoff=1)
            panel = Image.new("L", (cell_width, image_height), 255)
            panel.paste(
                structure,
                ((cell_width - structure.width) // 2, (image_height - structure.height) // 2),
            )
        x = (index % columns) * cell_width
        y = (index // columns) * (image_height + label_height)
        sheet.paste(panel.convert("RGB"), (x, y))
        match = re.match(r"t_(\d+)", path.stem)
        timestamp = f" t={int(match.group(1)) / 1000:.2f}s" if match else ""
        label = (
            f"S{shot['shot_id']}-{position}{timestamp} "
            f"({float(shot['start']):.2f}-{float(shot['end']):.2f}s)"
        )
        draw.rectangle((x, y + image_height, x + cell_width, y + image_height + label_height), fill="white")
        draw.text((x + 8, y + image_height + 7), label, fill="black")
    sheet.save(output_path, "JPEG", quality=92)
    return {
        "status": "generated",
        "method": "blurred posterized grayscale masses plus edges to preserve composition while reducing identity detail",
        "shots_included": len({str(item[0]["shot_id"]) for item in selected}),
        "panels_included": len(selected),
        "path": output_path.name,
        "warning": "仍是参考视频衍生结构图；只有权利确认后才可上传。",
    }


def image_briefs(request: PackageRequest) -> list[dict[str, Any]]:
    subject = request.target_subject or "保留原主体（需确认身份与授权）"
    style = request.style_target or "与目标视频场景匹配的写实电影质感"
    return [
        {
            "id": "IMG-01",
            "filename": "character_identity_anchor.png",
            "model_candidate": "Seedream 5.0 Lite（当前账号可用性待核）",
            "purpose": "只锁定人物身份、服装和比例，不承担动作或场景职责。",
            "prompt": (
                f"为视频角色一致性生成一张干净的角色身份锚点图：{subject}。"
                "同一人物，正面半身、左右三分之二侧面、全身站姿组成清晰四宫格；"
                "统一发型、面部结构、服装、配饰和身体比例；中性灰摄影棚背景，"
                "柔和均匀光，无动作夸张、无道具、无文字、无Logo、无水印。"
            ),
            "status": "needs_generation_and_visual_review",
        },
        {
            "id": "IMG-02",
            "filename": "character_action_anchor.png",
            "model_candidate": "Seedream 5.0 Lite（当前账号可用性待核）",
            "purpose": "锁定参考视频中最难动作的姿态与服装形变。",
            "prompt": (
                f"同一人物：{subject}。生成一张动作研究图，严格保持 IMG-01 的身份、"
                "服装和身体比例。动作内容必须在逐镜检查后替换为参考视频最难动作；"
                "全身完整入镜，四肢不裁切，受力合理，背景简洁，"
                f"视觉质感为{style}，无文字、无Logo、无水印。"
            ),
            "status": "needs_shot_annotation_then_generation",
        },
        {
            "id": "IMG-03",
            "filename": "scene_style_anchor.png",
            "model_candidate": "Seedream 5.0 Lite（当前账号可用性待核）",
            "purpose": "只锁定场景、光线、色彩和材质，不锁人物。",
            "prompt": (
                f"生成无人物的场景与风格锚点图。目标风格：{style}。"
                "构图、光线方向和主要空间层次在逐镜检查后填写；保留足够人物活动空间，"
                "无人物、无Logo、无品牌文字、无水印。"
            ),
            "status": "needs_shot_annotation_then_generation",
        },
    ]


def shot_rows(shots: list[dict[str, Any]], rules: dict[str, list[str]]) -> list[dict[str, Any]]:
    rows = []
    for shot in shots:
        rows.append({
            "shot_id": shot["shot_id"],
            "start": shot["start"],
            "end": shot["end"],
            "duration": shot["duration"],
            "evidence_frame": representative_frame(shot) or "",
            "hard_lock": "时间、顺序、动作节拍、剪辑功能",
            "visual_description": "NEEDS_VISUAL_ANNOTATION",
            "subject_action": "NEEDS_VISUAL_ANNOTATION",
            "camera_and_composition": "NEEDS_VISUAL_ANNOTATION",
            "audio_cue": "NEEDS_AUDIO_ANNOTATION",
            "replace": "；".join(rules["replace"]),
            "do_not_reference": "；".join(rules["do_not_reference"]),
            "confidence": "UNKNOWN",
        })
    return rows


def prompt_text(
    request: PackageRequest,
    shots: list[dict[str, Any]],
    rules: dict[str, list[str]],
) -> str:
    subject = request.target_subject or "原主体（仅在授权确认后保留）"
    camera = request.camera_change or "严格参考原视频景别、机位、构图与运镜"
    style = request.style_target or "参考原片的光线、色彩和材质关系"
    shot_lines = [
        (
            f"- {float(shot['start']):.2f}–{float(shot['end']):.2f}s / 镜头 {shot['shot_id']}："
            "严格锁定该镜头的时间功能、动作节拍和剪辑点；"
            "[NEEDS_VISUAL_ANNOTATION] 具体画面、动作和运镜需根据证据帧补全。"
        )
        for shot in shots
    ]
    return "\n".join([
        "# Seedance 导演提示词工作稿",
        "",
        "## 素材职责",
        "",
        "- @结构分镜图：只参考镜头顺序、构图骨架、景别和剪辑时间，不参考原人物身份。",
        "- @人物身份图：只参考目标人物面部、发型、服装、配饰和身体比例。",
        "- @动作锚点图：只参考最难动作姿态与服装形变。",
        "- @场景风格图：只参考空间、光线、色彩和材质，不参考人物。",
        "- @参考视频：只参考动作节拍、镜头运动、剪辑点和经确认的声音节奏。",
        "",
        "## 全局导演指令",
        "",
        f"创作目标：{request.goal}。",
        f"目标人物：{subject}。",
        f"镜头策略：{camera}。",
        f"视觉策略：{style}。",
        f"目标产品/道具：{request.product or '无或待确认'}。",
        "全片中目标人物的脸部结构、发型、服装、配饰、年龄感和身体比例必须一致。",
        "镜头之间保持空间方向、动作接点、视线方向、道具状态和光线方向连续。",
        "",
        "## 逐镜时间线",
        "",
        *shot_lines,
        "",
        "## 明确不参考",
        "",
        *[f"- {item}" for item in rules["do_not_reference"]],
        "",
        "## 负面约束",
        "",
        "不要混入原人物面孔、服装或身体特征；不要出现身份漂移、换脸痕迹、多人融合、"
        "五官突变、服装跳变、肢体畸形、手指数错误、动作断裂、越轴、景别无故变化、"
        "运镜抖动、字幕乱码、Logo、水印或未经指定的品牌元素。",
        "",
        "## 使用状态",
        "",
        "本稿是确定性骨架，逐镜视觉和声音字段尚未由人工/模型检查证据帧补齐时，不可直接生成。",
    ])


def execution_card(
    request: PackageRequest,
    metadata: dict[str, Any],
    duration: dict[str, Any],
    ratio: str,
) -> str:
    rights_block = (
        "已确认，可按素材职责上传"
        if request.rights_status == "confirmed"
        else "未知；确认拥有或获授权前，不上传参考视频或衍生分镜图"
    )
    identity_block = (
        "已确认"
        if request.identity_consent in {"confirmed", "not-applicable"}
        else "未知；真人身份图上传与人物替换前必须确认同意或合法授权"
    )
    return "\n".join([
        "# Seedance 官网执行卡",
        "",
        "- 模型候选：Seedance 2.0（当前账号可用性待核）",
        "- 官网模式候选：全方位/全能参考；若账号提供定向视频编辑，可做小范围对照测试",
        f"- 创作策略：{request.strategy}",
        f"- 比例候选：{ratio}",
        f"- 时长方案：{duration['recommended']}",
        "- 清晰度：从当前账号实际可选项中选择；不得用提示词中的分辨率形容词代替官网参数",
        "- 声音：参考音频只承担明确的节奏/音效职责；口播和版权音乐另行确认",
        "- 图片模型候选：Seedream 5.0 Lite，用于人物、动作和场景锚点；账号可用性待核",
        f"- 参考素材权利：{rights_block}",
        f"- 真人身份同意：{identity_block}",
        "",
        "## 建议上传顺序",
        "",
        "1. @图片1：structure_storyboard.jpg，只参考结构、景别、构图骨架和时间顺序",
        "2. @图片2：character_identity_anchor.png，只参考目标人物身份与服装",
        "3. @图片3：character_action_anchor.png，只参考难动作",
        "4. @图片4：scene_style_anchor.png，只参考场景、光线、色彩与材质",
        "5. @视频1：原参考视频，只参考动作节拍、运镜、剪辑点及获准声音",
        "",
        "未生成或未人工检查的图片不得上传；未使用素材不要占用参考位。",
        f"源文件 SHA-256：{metadata.get('source_sha256', 'UNKNOWN')}",
    ])


def build_package(request: PackageRequest) -> Path:
    validate_request(request)
    metadata, shots = load_evidence(request.evidence_dir)
    target = output_directory(request)
    rules = strategy_rules(request)
    duration = duration_plan(float(metadata.get("duration") or 0.0))
    width, height = source_dimensions(metadata)
    ratio = nearest_ratio(width, height)
    rows = shot_rows(shots, rules)
    briefs = image_briefs(request)

    target.mkdir(parents=True, exist_ok=False)
    storyboard = create_structure_storyboard(
        request.evidence_dir, shots, target / "structure_storyboard.jpg"
    )
    write_json(target / "replication_manifest.json", {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "strategy": request.strategy,
        "goal": request.goal,
        "source_evidence": str(request.evidence_dir),
        "source_sha256": metadata.get("source_sha256"),
        "rights_status": request.rights_status,
        "identity_consent": request.identity_consent,
        "ratio_candidate": ratio,
        "duration_plan": duration,
        "control_layers": rules,
        "structure_storyboard": storyboard,
        "claims": {
            "deterministic_scaffold_created": True,
            "visual_shot_annotations_complete": False,
            "reference_images_generated": False,
            "seedance_account_verified": False,
            "seedance_generation_tested": False,
            "perfect_replication_guaranteed": False,
        },
    })
    write_json(target / "images_to_generate.json", {"images": briefs})
    with (target / "shot_lock_table.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_json(target / "shot_annotations.json", {"shots": rows})
    write_text(target / "seedance_prompt_workbench.md", prompt_text(request, shots, rules))
    write_text(target / "Seedance官网执行卡.md", execution_card(request, metadata, duration, ratio))
    write_text(target / "人工补全与验收.md", "\n".join([
        "# 人工补全与验收",
        "",
        "## 生成前必须完成",
        "",
        "- [ ] 逐镜查看证据帧并补全 shot_annotations.json 的画面、动作、机位和声音字段",
        "- [ ] 确认参考视频及衍生结构图的上传权利",
        "- [ ] 确认真人身份参考与人物替换授权",
        "- [ ] 生成并逐张检查三类锚点图；不一致的图片不得混用",
        "- [ ] 在当前 Seedance 账号确认模型、模式、比例、清晰度、时长和素材上限",
        "- [ ] 将最终上传顺序回填到官网执行卡并核对 @编号",
        "",
        "## 生成后质量分",
        "",
        "- 镜头顺序与时长 25",
        "- 人物身份与服装一致性 20",
        "- 动作与动作接点 15",
        "- 运镜、机位与轴线 15",
        "- 构图与主体位置 10",
        "- 光线、色彩与目标风格 10",
        "- 声音节奏与同步 5",
        "",
        "总分仅用于比较迭代版本，不代表客观“完美”。任一身份漂移、肢体错误、"
        "关键动作缺失、顺序错误或未授权元素出现，都应判定为阻断问题。",
    ]))
    return target


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--strategy", required=True, choices=STRATEGIES)
    parser.add_argument("--target-subject")
    parser.add_argument("--camera-change")
    parser.add_argument("--style-target")
    parser.add_argument("--product")
    parser.add_argument("--goal", default="高保真迁移参考视频结构")
    parser.add_argument("--rights-status", choices=("confirmed", "unknown"), default="unknown")
    parser.add_argument(
        "--identity-consent",
        choices=("confirmed", "not-applicable", "unknown"),
        default="unknown",
    )
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    request = PackageRequest(
        evidence_dir=args.evidence.resolve(),
        strategy=args.strategy,
        target_subject=args.target_subject,
        camera_change=args.camera_change,
        style_target=args.style_target,
        product=args.product,
        goal=args.goal,
        rights_status=args.rights_status,
        identity_consent=args.identity_consent,
        output_dir=args.output_dir,
    )
    target = build_package(request)
    print(json.dumps({
        "status": "scaffold_created",
        "output": str(target),
        "visual_annotation_complete": False,
        "images_generated": False,
        "seedance_tested": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PackageError as exc:
        print(f"[replication-package] {exc}", file=sys.stderr)
        raise SystemExit(2)
