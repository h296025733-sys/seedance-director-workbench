---
name: viral-video-breakdown
description: Produce an evidence-grounded director-level breakdown and reconstruction map of a reference video, including the first three seconds, per-shot visuals, camera movement, edit rhythm, text, speech, music, sound effects, product presentation, retention function, conversion function, confidence, evidence paths, and hard-lock/soft-lock/replace/vary controls. Use when Codex is asked to analyze, reverse-engineer, remake, replicate, replace a person in, change the camera or style of, or explain a reference video, hook, shot structure, pacing, transition, audio beat, product reveal, or CTA.
---

# Viral Video Breakdown

Read an existing evidence package. If it does not exist, use `watch-video` first.

## Workflow

1. Read `metadata.json`, `shots.json`, `transcript.json`, `audio_analysis.json`, `extraction_report.md`, and referenced frames.
2. Separate every statement into:
   - **A — direct fact**: visible, audible, measured, or transcribed evidence.
   - **B — reasonable inference**: supported by multiple observations but not directly proven.
   - **C — unknown**: insufficient evidence.
3. Analyze 0–0.5 s, 0.5–1 s, 1–2 s and 2–3 s separately.
4. Identify first product appearance, conflict, visual change, emotional change, transition, sound impact, and final CTA.
5. For each shot record time range, duration, frame paths, shot scale, angle, composition, subject position/action, camera movement, focus, edit point, transition, on-screen text, subtitle, speech, music, sound, synchronization, light, color, product/selling point, shot function, retention function, conversion function, confidence, and evidence path.
6. For reconstruction work, add:
   - `HARD_LOCK`: timing, order, action beat, edit point, and any camera property that must remain.
   - `SOFT_LOCK`: relationships that may adapt without losing the shot function.
   - `REPLACE`: person, clothing, product, brand, copy, or scene.
   - `VARY`: camera, angle, movement, lighting, or style requested by the user.
   - `DO_NOT_REFERENCE`: identity, logo, watermark, copyrighted copy, or unrelated visual details.
7. Render analysis with `templates/爆款拆解报告模板.md`; render reconstruction work with `templates/高保真复刻执行包模板.md`.

## Guardrails

- Do not claim natural traffic, no paid promotion, account weight, targeting, transaction rate, or a causal viral mechanism from video evidence alone.
- Mark copyright-sensitive assets—people, brands, logos, copy, and unique creative expression—as non-transferable unless permission is established.
- Distinguish transferable structure, shot function, action rhythm, and conversion logic from elements that must be replaced.
- If frames, transcript, or audio evidence are absent, explicitly lower confidence rather than filling gaps.
- Never infer a precise pose, lens, focal length, camera path, or lighting setup from a single ambiguous frame; mark it as a hypothesis to test.
