#!/usr/bin/env python3
"""Read-only environment diagnostics for the Seedance workspace."""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent


def configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def find_command(name: str) -> tuple[str | None, str | None]:
    if name in {"python", "pip", "yt-dlp"}:
        executable_name = {
            "python": "python.exe",
            "pip": "pip.exe",
            "yt-dlp": "yt-dlp.exe",
        }[name]
        candidate = WORKSPACE_ROOT / ".venv" / "Scripts" / executable_name
        if candidate.is_file():
            return str(candidate.resolve()), "project_venv"
    path = shutil.which(name)
    if path:
        return path, "PATH"
    if name in {"ffmpeg", "ffprobe"}:
        suffix = ".exe" if os.name == "nt" else ""
        candidates = sorted(
            (WORKSPACE_ROOT / "tools" / "vendor").glob(
                f"ffmpeg-*-essentials_build/bin/{name}{suffix}"
            ),
            reverse=True,
        )
        if candidates:
            return str(candidates[0].resolve()), "project_vendor"
    return None, None


def command_version(name: str, args: list[str]) -> dict:
    path, origin = find_command(name)
    if not path:
        return {"name": name, "status": "missing", "path": None, "version": None}
    try:
        result = subprocess.run(
            [path, *args], capture_output=True, text=True, timeout=10, check=False
        )
        text = (result.stdout or result.stderr).strip().splitlines()
        return {
            "name": name,
            "status": "available" if result.returncode == 0 else "error",
            "path": path,
            "origin": origin,
            "version": text[0] if text else None,
            "returncode": result.returncode,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "name": name,
            "status": "error",
            "path": path,
            "origin": origin,
            "error": str(exc),
        }


def memory_info() -> dict:
    if os.name != "nt":
        return {"status": "not_implemented_for_platform"}
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-CimInstance Win32_OperatingSystem | "
                "Select-Object TotalVisibleMemorySize,FreePhysicalMemory | "
                "ConvertTo-Json -Compress"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return {"status": "error", "message": result.stderr.strip()}
    raw = json.loads(result.stdout)
    return {
        "status": "available",
        "total_gb": round(int(raw["TotalVisibleMemorySize"]) / 1024 / 1024, 2),
        "free_gb": round(int(raw["FreePhysicalMemory"]) / 1024 / 1024, 2),
    }


def project_environment(name: str, modules: tuple[str, ...]) -> dict:
    python_path = WORKSPACE_ROOT / name / "Scripts" / "python.exe"
    if not python_path.is_file():
        return {"status": "missing", "python": str(python_path), "modules": {}}
    code = (
        "import importlib.util,json,sys; "
        f"mods={modules!r}; "
        "print(json.dumps({'version':sys.version.split()[0],"
        "'modules':{m:bool(importlib.util.find_spec(m)) for m in mods}}))"
    )
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [str(python_path), "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
        env=environment,
    )
    if result.returncode != 0:
        return {
            "status": "error",
            "python": str(python_path),
            "message": result.stderr.strip(),
        }
    payload = json.loads(result.stdout)
    return {"status": "available", "python": str(python_path), **payload}


def main() -> int:
    configure_utf8_stdio()
    usage = shutil.disk_usage(WORKSPACE_ROOT)
    commands = [
        command_version("git", ["--version"]),
        command_version("python", ["--version"]),
        command_version("pip", ["--version"]),
        command_version("node", ["--version"]),
        command_version("npm", ["--version"]),
        command_version("npx", ["--version"]),
        command_version("ffmpeg", ["-version"]),
        command_version("ffprobe", ["-version"]),
        command_version("yt-dlp", ["--version"]),
        command_version("codex", ["--version"]),
        command_version("nvidia-smi", ["--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"]),
        command_version("nvcc", ["--version"]),
    ]
    modules = {
        name: bool(importlib.util.find_spec(name))
        for name in (
            "PIL",
            "numpy",
            "cv2",
            "scenedetect",
            "faster_whisper",
            "whisper",
            "torch",
            "yaml",
        )
    }
    report = {
        "schema_version": 1,
        "workspace": str(WORKSPACE_ROOT),
        "platform": platform.platform(),
        "python_runtime": {
            "executable": sys.executable,
            "version": sys.version.splitlines()[0],
        },
        "commands": commands,
        "python_modules": modules,
        "project_environments": {
            "core": project_environment(
                ".venv", ("cv2", "scenedetect", "faster_whisper", "yt_dlp", "yaml", "PIL")
            ),
            "pose": project_environment(".venv-pose", ("mediapipe", "cv2")),
            "audit": project_environment(".venv-audit", ("pip_audit",)),
        },
        "memory": memory_info(),
        "disk": {
            "total_gb": round(usage.total / 1024**3, 2),
            "used_gb": round(usage.used / 1024**3, 2),
            "free_gb": round(usage.free / 1024**3, 2),
        },
        "skill_paths": {
            "project": str(WORKSPACE_ROOT / ".agents" / "skills"),
            "project_exists": (WORKSPACE_ROOT / ".agents" / "skills").is_dir(),
            "global_checked_but_not_modified": str(Path.home() / ".codex" / "skills"),
        },
        "notes": [
            "This report is read-only and does not install or configure software.",
            "A bundled Codex Python runtime is not the same as a system PATH installation.",
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    required = {item["name"]: item["status"] for item in commands}
    return 0 if required["ffmpeg"] == required["ffprobe"] == "available" else 2


if __name__ == "__main__":
    raise SystemExit(main())
