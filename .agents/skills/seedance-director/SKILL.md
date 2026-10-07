---
name: seedance-director
description: Build a constrained, executable Seedance directing and reconstruction package from a user brief, target character or product, evidence-backed reference breakdown, current website capabilities, material plan, and confirmed house style. Use when Codex is asked to remake a video, replace its character, preserve its shots while changing angle or style, generate the needed reference images and prompts, or produce an original/reference/hybrid concept, storyboard, second-by-second timeline, camera and sound design, Seedance prompt, quality check, or generation-failure correction.
---

# Seedance Director

Reduce uncontrolled generation by deciding the creative structure and execution constraints before writing the final prompt.

## Workflow

1. Read workspace rules and relevant current Seedance knowledge.
2. Choose and justify:
   - `REFERENCE`: transfer structure or shot function without copying protected expression.
   - `ORIGINAL`: design from product, audience and objective.
   - `HYBRID`: retain validated structural functions while replacing people, product, brand, scene and protected assets.
3. If a reference is involved, require an evidence-backed `viral-video-breakdown` output.
4. For a remake, read `knowledge/高保真结构迁移方法.md` and create the deterministic scaffold:

```powershell
python .\tools\build_replication_package.py --evidence "<evidence-dir>" --strategy character-swap --target-subject "<target>"
```

5. Visually inspect each evidence frame. Replace all `NEEDS_VISUAL_ANNOTATION` fields before producing a direct-paste prompt.
6. Create or edit the required image anchors only after the user provides the target identity/reference or a sufficient fictional-character brief:
   - identity anchor;
   - difficult-action anchor;
   - scene/style anchor.
   Use Seedream 5.0 Lite when available or the approved image-generation tool. Inspect every image and reject identity drift, clothing drift, pose errors, extra limbs, logos, text, or conflicting responsibilities.
7. Read only confirmed style rules. Mark unconfirmed choices `待确认`.
8. Use `seedance-ui-planner` to put the website execution card before any formal prompt.
9. Build the output in this order:
   - task understanding, creation type, goal, audience, platform;
   - first-three-second hook and creative concept;
   - website execution card;
   - material needs, upload order and @ mapping;
   - storyboard and second-by-second timeline;
   - character/product actions, camera, edit, transition, light, color, sound, voiceover and subtitles;
   - continuity and negative constraints;
   - director full version and concise direct-paste version;
   - failure risks, first correction prompt, second alternative, missing materials.
10. For reconstruction, additionally include all image files, the control-layer matrix, the shot-lock table, and the 100-point comparison scorecard.
11. Run the checklist in `templates/Seedance执行包模板.md` and `templates/高保真复刻执行包模板.md`.

## Constraints

- Do not generate or submit to Seedance, log into an account, upload local media, or consume credits without explicit authorization.
- Do not hardcode changing parameters.
- Remove duplicate adjectives, conflicting camera terms and impossible event density from the paste version.
- A generation result is not validated until the account was used and the output inspected; static planning is not end-to-end verification.
- Never promise perfect replication. State the fidelity target, hard failures, evidence, tested scope, and remaining stochastic uncertainty.
- Do not upload a reference, derivative storyboard, or real-person identity image until rights and consent are confirmed.
