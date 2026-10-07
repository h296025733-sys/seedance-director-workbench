#!/usr/bin/env python3
"""Dependency-free structural validation for project-local Codex skills.

This checks the subset of the skill contract that can be verified without
PyYAML or a fresh Codex task. It does not claim live discovery by Codex.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
QUOTED_VALUE_RE = re.compile(
    r'^\s{2,}(description|short_description):\s*"([^"]+)"\s*$', re.MULTILINE
)


def parse_frontmatter(text: str) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    if not text.startswith("---\n"):
        return {}, ["SKILL.md must start with YAML frontmatter"]
    try:
        closing = text.index("\n---\n", 4)
    except ValueError:
        return {}, ["SKILL.md frontmatter is not closed"]
    fields: dict[str, str] = {}
    for raw in text[4:closing].splitlines():
        if not raw.strip():
            continue
        if ":" not in raw:
            errors.append(f"invalid frontmatter line: {raw!r}")
            continue
        key, value = raw.split(":", 1)
        fields[key.strip()] = value.strip().strip('"')
    return fields, errors


def validate_skill(skill_dir: Path) -> dict[str, object]:
    errors: list[str] = []
    skill_file = skill_dir / "SKILL.md"
    agent_file = skill_dir / "agents" / "openai.yaml"

    try:
        skill_text = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return {"skill": skill_dir.name, "ok": False, "errors": [str(exc)]}

    fields, frontmatter_errors = parse_frontmatter(skill_text)
    errors.extend(frontmatter_errors)
    name = fields.get("name", "")
    description = fields.get("description", "")
    extra = sorted(set(fields) - {"name", "description"})

    if name != skill_dir.name:
        errors.append(f"frontmatter name {name!r} does not match directory")
    if not NAME_RE.fullmatch(name) or len(name) > 64:
        errors.append("name must be kebab-case and no more than 64 characters")
    if not description or len(description) > 1024:
        errors.append("description must contain 1-1024 characters")
    if extra:
        errors.append(f"unexpected frontmatter fields: {', '.join(extra)}")
    if len(skill_text.splitlines()) < 8:
        errors.append("SKILL.md has too little workflow content")

    try:
        agent_text = agent_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"agents/openai.yaml: {exc}")
    else:
        if not re.search(r"(?m)^interface:\s*$", agent_text):
            errors.append("openai.yaml lacks interface mapping")
        values = {match.group(1): match.group(2) for match in QUOTED_VALUE_RE.finditer(agent_text)}
        if not (values.get("description") or values.get("short_description")):
            errors.append("openai.yaml lacks quoted interface description")
        if not re.search(r'(?m)^\s{2,}display_name:\s*"[^"]+"\s*$', agent_text):
            errors.append("openai.yaml lacks quoted interface.display_name")
        if not re.search(r'(?m)^\s{2,}default_prompt:\s*"[^"]+"\s*$', agent_text):
            errors.append("openai.yaml lacks quoted interface.default_prompt")

    return {"skill": skill_dir.name, "ok": not errors, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".agents" / "skills",
    )
    args = parser.parse_args()

    skill_dirs = sorted(path for path in args.root.iterdir() if path.is_dir())
    results = [validate_skill(path) for path in skill_dirs]
    payload = {
        "validator_scope": "dependency-free structural checks; not live Codex discovery",
        "root": str(args.root.resolve()),
        "skills_found": len(results),
        "ok": bool(results) and all(item["ok"] for item in results),
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
