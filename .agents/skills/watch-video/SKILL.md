---
name: watch-video
description: Convert a local video or an explicitly authorized network video into a traceable evidence package containing metadata, timestamps, shot boundaries, keyframes, hook frames, transition frames, transcript artifacts, audio metadata, a contact sheet, and an extraction report. Use when Codex is asked to watch, inspect, read, transcribe, sample, extract frames from, reverse-engineer, remake, or establish evidence for a video before analysis, character replacement, shot variation, style transfer, or directing.
---

# Watch Video

Create evidence before interpretation. Default to local-only processing and never upload media without explicit authorization.

## Workflow

1. Read the workspace `AGENTS.md`, then run `tools/doctor.py` or `tools/doctor.ps1`.
2. Resolve the source:
   - Accept a local file by default.
   - Require explicit user authorization and `--allow-network` for a URL.
   - Never use external transcription unless the user separately authorizes the exact service and upload.
3. Select one mode:
   - `FAST`: metadata and sparse frames; fastest orientation.
   - `BALANCED`: ordinary shot sampling and local subtitle extraction.
   - `DIRECTOR`: denser shots, first/middle/last frames, transitions and audio metadata.
   - `HOOK_DENSE`: sample 0–1 s at about 5 fps and 1–3 s at about 4 fps, then use shot-aware sampling.
4. Run the deterministic extractor:

```powershell
.\.venv\Scripts\python.exe .\tools\watch_video.py `
  --source "<local-video>" --task-name "<任务名>" --mode HOOK_DENSE
```

The project `.venv` is the supported runtime. `--scene-detector auto` uses the
installed PySceneDetect AdaptiveDetector and records any fallback to FFmpeg.
For media without embedded subtitles, local CPU transcription is opt-in:

```powershell
.\.venv\Scripts\python.exe .\tools\watch_video.py `
  --source "<local-video>" --task-name "<任务名>" --mode DIRECTOR `
  --local-transcription
```

This uses the D-drive `models/faster-whisper-small` model with CPU INT8 and
does not upload media. Treat every transcript as review-required.

5. Require output under `outputs/<任务名>/evidence/`:
   - `metadata.json`
   - `transcript.json`
   - `transcript.srt`
   - `shots.json`
   - `shots.csv`
   - `keyframes/`
   - `hook_frames/`
   - `transition_frames/`
   - `contact_sheet.jpg`
   - `audio_analysis.json`
   - `extraction_report.md`
6. Verify the original file was not modified. Record missing dependencies, unavailable transcript, failed subtitle extraction, and skipped features in the report.
7. For remake or replacement work, run `tools/build_replication_package.py` only after evidence exists. Its deterministic output is a scaffold; visually inspect the referenced frames before filling shot descriptions or generating images.
8. Do not describe a dependency preflight, dry run, static check, or synthetic test as successful video extraction.
9. For identity-neutral motion evidence, run `tools/extract_pose_reference.py`
   with `.venv-pose`. Its stick-figure video omits facial landmarks. Keep its
   status as internal evidence until the target Seedance interface accepts it
   in an actual upload/generation test.

## Evidence Rules

- Preserve timestamps and source paths for every frame or claim.
- Use `HIGH`, `MEDIUM`, `LOW`, or `UNKNOWN` confidence only.
- Treat captions and speech-to-text as fallible; retain source and method.
- Do not infer performance metrics, audience targeting, paid distribution, conversion rate, or causal “viral” effects from the video.
- Keep originals read-only; write all derived media to the evidence directory.
- Confirm the user owns or may use a reference before preparing any derivative structure image for upload.
