from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


WORKSPACE = Path(__file__).resolve().parent.parent
MODULE_PATH = WORKSPACE / "tools" / "build_replication_package.py"
SPEC = importlib.util.spec_from_file_location("build_replication_package", MODULE_PATH)
assert SPEC and SPEC.loader
replication = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = replication
SPEC.loader.exec_module(replication)


class ReplicationPackageTests(unittest.TestCase):
    def make_evidence(self, root: Path, duration: float = 5.2) -> Path:
        evidence = root / "evidence"
        evidence.mkdir(parents=True)
        frames = evidence / "keyframes"
        frames.mkdir()
        Image.new("RGB", (320, 180), "#cc3344").save(frames / "t_000000500.jpg")
        Image.new("RGB", (320, 180), "#3366cc").save(frames / "t_000003500.jpg")
        metadata = {
            "duration": duration,
            "source_sha256": "a" * 64,
            "video_streams": [{"width": 1080, "height": 1920}],
        }
        shots = {
            "shots": [
                {
                    "shot_id": 1,
                    "start": 0.0,
                    "end": 2.0,
                    "duration": 2.0,
                    "keyframes": ["keyframes/t_000000500.jpg"],
                },
                {
                    "shot_id": 2,
                    "start": 2.0,
                    "end": duration,
                    "duration": round(duration - 2.0, 3),
                    "keyframes": ["keyframes/t_000003500.jpg"],
                },
            ]
        }
        (evidence / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
        )
        (evidence / "shots.json").write_text(
            json.dumps(shots, ensure_ascii=False), encoding="utf-8"
        )
        return evidence

    def test_character_swap_requires_target(self) -> None:
        with tempfile.TemporaryDirectory(dir=WORKSPACE / "outputs") as temporary:
            evidence = self.make_evidence(Path(temporary))
            with self.assertRaises(replication.PackageError):
                replication.validate_request(
                    replication.PackageRequest(
                        evidence_dir=evidence,
                        strategy="character-swap",
                    )
                )

    def test_builds_traceable_scaffold_without_claiming_generation(self) -> None:
        with tempfile.TemporaryDirectory(dir=WORKSPACE / "outputs") as temporary:
            root = Path(temporary)
            evidence = self.make_evidence(root)
            request = replication.PackageRequest(
                evidence_dir=evidence,
                strategy="character-swap",
                target_subject="虚构的短发成年女性，红色夹克",
                rights_status="confirmed",
                identity_consent="not-applicable",
            )
            target = replication.build_package(request)
            expected = {
                "replication_manifest.json",
                "images_to_generate.json",
                "shot_lock_table.csv",
                "shot_annotations.json",
                "seedance_prompt_workbench.md",
                "Seedance官网执行卡.md",
                "人工补全与验收.md",
                "structure_storyboard.jpg",
            }
            self.assertTrue(expected.issubset({path.name for path in target.iterdir()}))
            manifest = json.loads(
                (target / "replication_manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["claims"]["deterministic_scaffold_created"])
            self.assertFalse(manifest["claims"]["reference_images_generated"])
            self.assertFalse(manifest["claims"]["seedance_generation_tested"])
            self.assertFalse(manifest["claims"]["perfect_replication_guaranteed"])
            self.assertEqual(
                manifest["structure_storyboard"]["status"], "generated"
            )
            self.assertEqual(manifest["ratio_candidate"].split("（", 1)[0], "9:16")
            self.assertEqual(
                manifest["duration_plan"]["segments"][0]["website_duration_candidate"], 6
            )

            prompt = (target / "seedance_prompt_workbench.md").read_text(encoding="utf-8")
            self.assertIn("@人物身份图：只参考目标人物", prompt)
            self.assertIn("NEEDS_VISUAL_ANNOTATION", prompt)
            self.assertIn("不要混入原人物面孔", prompt)

            with (target / "shot_lock_table.csv").open(
                encoding="utf-8-sig", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["visual_description"], "NEEDS_VISUAL_ANNOTATION")
            with Image.open(target / "structure_storyboard.jpg") as storyboard:
                self.assertEqual(storyboard.size, (720, 233))

    def test_long_video_is_split_and_output_refuses_overwrite(self) -> None:
        plan = replication.duration_plan(31.1)
        self.assertEqual(len(plan["segments"]), 3)
        self.assertLessEqual(
            max(item["website_duration_candidate"] for item in plan["segments"]), 15
        )
        with tempfile.TemporaryDirectory(dir=WORKSPACE / "outputs") as temporary:
            root = Path(temporary)
            evidence = self.make_evidence(root)
            target = root / "replication_package"
            target.mkdir()
            (target / "preserve.txt").write_text("keep", encoding="utf-8")
            request = replication.PackageRequest(
                evidence_dir=evidence,
                strategy="style-variation",
                style_target="复古胶片",
                output_dir=target,
            )
            with self.assertRaises(replication.PackageError):
                replication.build_package(request)
            self.assertEqual(
                (target / "preserve.txt").read_text(encoding="utf-8"), "keep"
            )

    def test_cli_builds_synthetic_evidence_package(self) -> None:
        with tempfile.TemporaryDirectory(dir=WORKSPACE / "outputs") as temporary:
            root = Path(temporary)
            evidence = self.make_evidence(root)
            result = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--evidence",
                    str(evidence),
                    "--strategy",
                    "hybrid",
                    "--target-subject",
                    "虚构成年男性，蓝色外套",
                    "--camera-change",
                    "把正面平视改为低机位三分之二侧面",
                    "--style-target",
                    "冷色电影夜景",
                    "--rights-status",
                    "confirmed",
                    "--identity-consent",
                    "not-applicable",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "scaffold_created")
            self.assertFalse(payload["images_generated"])
            target = Path(payload["output"])
            self.assertTrue((target / "structure_storyboard.jpg").is_file())
            manifest = json.loads(
                (target / "replication_manifest.json").read_text(encoding="utf-8")
            )
            self.assertIn(
                "把正面平视改为低机位三分之二侧面",
                manifest["control_layers"]["vary"][0],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
