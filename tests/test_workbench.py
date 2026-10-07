from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


WORKSPACE = Path(__file__).resolve().parent.parent
MODULE_PATH = WORKSPACE / "tools" / "watch_video.py"
SPEC = importlib.util.spec_from_file_location("watch_video", MODULE_PATH)
assert SPEC and SPEC.loader
watch_video = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watch_video)


class WorkbenchPolicyTests(unittest.TestCase):
    def test_duration_prefers_video_stream_over_longer_audio_tail(self) -> None:
        probe = {
            "format": {"duration": "5.088005"},
            "streams": [
                {"codec_type": "video", "duration": "5.016667"},
                {"codec_type": "audio", "duration": "5.088005"},
            ],
        }
        self.assertAlmostEqual(watch_video.duration_from_probe(probe), 5.016667)

    def test_chinese_space_and_special_task_names(self) -> None:
        for value in ("中文 视频", "产品（A）& 测试", "竖屏-5秒"):
            self.assertEqual(watch_video.validate_task_name(value), value)

    def test_windows_invalid_and_reserved_names(self) -> None:
        for value in ("CON", "AUX.txt", "bad/name", "bad:name", "..", "tail."):
            with self.assertRaises(watch_video.EvidenceError, msg=value):
                watch_video.validate_task_name(value)

    def test_long_chinese_path_and_containment(self) -> None:
        temporary = tempfile.mkdtemp(dir=WORKSPACE / "tests")
        base = Path(temporary)
        try:
            long_path = base
            for index in range(8):
                long_path /= f"很长的中文目录 {index:02d} abcdefghijklmnopqrstuvwxyz"
            extended = Path(watch_video.windows_extended_path(long_path))
            extended.mkdir(parents=True)
            file_path = extended / "素材 文件 [测试].txt"
            file_path.write_text("UTF-8 路径测试", encoding="utf-8")
            self.assertTrue(watch_video.is_within(long_path / file_path.name, base))
            self.assertGreater(len(str(file_path)), 260)
            self.assertEqual(file_path.read_text(encoding="utf-8"), "UTF-8 路径测试")
        finally:
            shutil.rmtree(watch_video.windows_extended_path(base, force=True))

    def test_output_must_stay_under_outputs(self) -> None:
        with self.assertRaises(watch_video.EvidenceError):
            watch_video.evidence_directory("x", str(WORKSPACE / "archive" / "x"))

    def test_nonempty_output_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory(dir=WORKSPACE / "outputs") as temporary:
            target = Path(temporary)
            (target / "已存在.txt").write_text("preserve", encoding="utf-8")
            with self.assertRaises(watch_video.EvidenceError):
                watch_video.evidence_directory("ignored", str(target))

    def test_json_utf8_and_existing_file_error(self) -> None:
        with tempfile.TemporaryDirectory(dir=WORKSPACE / "tests") as temporary:
            path = Path(temporary) / "中文 结果.json"
            watch_video.write_json(path, {"文本": "中英 mixed ✓"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["文本"], "中英 mixed ✓")
            with self.assertRaises(FileExistsError):
                watch_video.write_json(path, {"overwrite": True})

    def test_network_source_is_denied_by_default(self) -> None:
        with tempfile.TemporaryDirectory(dir=WORKSPACE / "tests") as temporary:
            with self.assertRaises(watch_video.EvidenceError):
                watch_video.obtain_source(
                    "https://example.com/video.mp4",
                    False,
                    None,
                    Path(temporary) / "network",
                )

    def test_missing_dependency_is_explicit(self) -> None:
        with self.assertRaises(watch_video.EvidenceError):
            watch_video.executable("definitely-not-a-real-seedance-tool")

    def test_subprocess_output_is_decoded_as_utf8(self) -> None:
        result = watch_video.run([
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write('中文路径 ✓'.encode('utf-8'))",
        ])
        self.assertEqual(result.stdout, "中文路径 ✓")

    def test_sampling_modes_are_bounded_and_hook_dense(self) -> None:
        shots = watch_video.build_shots(15.0, [1.0, 3.0, 8.0])
        fast = watch_video.sampling_times("FAST", 15.0, shots)
        hook = watch_video.sampling_times("HOOK_DENSE", 15.0, shots)
        self.assertLessEqual(len(fast), 24)
        self.assertLessEqual(len(hook), 140)
        self.assertGreater(len([value for value in hook if value <= 3]), 10)

    def test_scene_detector_auto_fallback_is_explicit(self) -> None:
        with mock.patch.object(
            watch_video,
            "detect_scene_times_adaptive",
            side_effect=watch_video.EvidenceError("optional dependency missing"),
        ), mock.patch.object(
            watch_video,
            "detect_scene_times_ffmpeg",
            return_value=[1.25],
        ):
            times, details = watch_video.detect_scene_times(
                "ffmpeg", Path("video.mp4"), detector="auto"
            )
        self.assertEqual(times, [1.25])
        self.assertEqual(details["method"], "ffmpeg_scene_filter")
        self.assertTrue(details["fallback"])
        self.assertIn("optional dependency missing", details["fallback_reason"])

    def test_scene_detector_rejects_invalid_parameters(self) -> None:
        with self.assertRaises(watch_video.EvidenceError):
            watch_video.detect_scene_times("ffmpeg", Path("x"), detector="unknown")
        with self.assertRaises(watch_video.EvidenceError):
            watch_video.detect_scene_times(
                "ffmpeg", Path("x"), adaptive_threshold=0
            )
        with self.assertRaises(watch_video.EvidenceError):
            watch_video.detect_scene_times(
                "ffmpeg", Path("x"), min_scene_len_frames=0
            )

    def test_srt_timestamp_rounding(self) -> None:
        self.assertEqual(watch_video.seconds_to_srt_timestamp(0), "00:00:00,000")
        self.assertEqual(watch_video.seconds_to_srt_timestamp(61.2346), "00:01:01,235")
        self.assertEqual(watch_video.seconds_to_srt_timestamp(-1), "00:00:00,000")

    def test_local_transcription_requires_complete_model(self) -> None:
        with tempfile.TemporaryDirectory(dir=WORKSPACE / "tests") as temporary:
            root = Path(temporary)
            with self.assertRaises(watch_video.EvidenceError):
                watch_video.transcribe_local(
                    root / "video.mp4",
                    root / "transcript.srt",
                    root / "missing-model",
                )

    def test_required_skill_frontmatter_and_metadata(self) -> None:
        for name in (
            "watch-video",
            "viral-video-breakdown",
            "seedance-ui-planner",
            "seedance-director",
        ):
            skill = (WORKSPACE / ".agents" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            metadata = (WORKSPACE / ".agents" / "skills" / name / "agents" / "openai.yaml").read_text(encoding="utf-8")
            self.assertIn(f"name: {name}", skill)
            self.assertIn("description:", skill)
            self.assertNotIn("TODO", skill)
            self.assertIn(f"${name}", metadata)

    def test_seedance_limits_json_is_valid(self) -> None:
        data = json.loads((WORKSPACE / "knowledge" / "Seedance素材限制表.json").read_text(encoding="utf-8"))
        self.assertFalse(data["platforms"]["user_current_website"]["account_verified"])
        self.assertFalse(data["platforms"]["user_current_website"]["generation_tested"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
