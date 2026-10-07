---
name: seedance-ui-planner
description: Choose a source-aware Seedance model and website execution configuration for original or reference-led generation, character replacement, camera variation, and style transfer: creation type, website mode, aspect ratio, resolution, duration, sound method, source assets, upload order, @ bindings, first/last-frame use, split generations, and expected risks. Use when Codex is asked which Seedance mode or parameters to select, how to upload and bind a reference video, structure board, character image, action image, scene image, or to create a Seedance website execution card before generation.
---

# Seedance UI Planner

Plan against current evidence, not remembered parameters.

## Required Reading

Read:

- `knowledge/Seedance当前能力与限制.md`
- `knowledge/Seedance来源索引.md`
- `knowledge/Seedance界面模式决策表.md`
- `knowledge/Seedance素材限制表.json`
- `knowledge/Seedance待实测功能.md`
- `knowledge/Seedance素材职责矩阵.md`
- `knowledge/高保真结构迁移方法.md` when a reference is being reconstructed or varied

## Decision Workflow

1. Determine `REFERENCE`, `ORIGINAL`, or `HYBRID`.
2. Inventory only the assets actually needed.
3. Choose the website mode:
   - Prefer all-round reference for mixed modalities, explicit @ roles, reference motion/camera/edit/audio, editing, extension, fusion, or HYBRID work.
   - Prefer first/last frame for strict opening and ending states with a describable intermediate path.
   - Recommend multi-frame only after current-account selectability and generation behavior are verified.
   - Treat subject reference, text generation, editing, extension, and fusion as separate entries until the current platform proves equivalence.
4. Select aspect ratio, resolution, duration and sound only from current official/platform/account evidence. Never assume one platform exposes another platform’s options.
5. Assign each uploaded item one clear core role and explicit non-reference content. Match @ numbers to upload order.
6. Identify conflicts, overload, continuity risks and whether multiple generations are safer.
7. For character replacement or controlled variation:
   - assign the structure board only to shot order/composition;
   - assign the identity image only to the new subject;
   - assign the action image only to the difficult pose;
   - assign the scene/style image only to environment and look;
   - assign the video only to explicitly retained motion, camera, edit, and audio dimensions;
   - explicitly state which original-person features must not be referenced.
8. If the source exceeds 15 seconds, create a continuity-aware split plan; do not imply one unsupported generation can reproduce it.
9. Output `templates/官网执行卡模板.md`.

## State Vocabulary

Keep these independent: `UI_VISIBLE`, `UI_SELECTABLE`, `OFFICIAL_DOCUMENTED`, `ACCOUNT_VERIFIED`, `GENERATION_TESTED`, `CURRENTLY_RECOMMENDED`, `NOTES`.

Never translate `UI_VISIBLE` into “verified usable.” Put changing price or points behind a dated interface observation.

Prefer a 4–5 second high-risk pilot before a full generation, but only after the user authorizes credit use. A successful prompt draft is not a successful generation.
