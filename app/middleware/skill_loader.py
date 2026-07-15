"""
SkillLoader — resolves skill dependencies and stitches instructions into the
system prompt.
"""

import json

from ..db import conn


def _fetch_all() -> dict[str, dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT skill_id, name, description, instructions, tags, dependencies, "
            "inject_full, status, version FROM summit_skills WHERE status = 'active'"
        ).fetchall()
    return {
        r[0]: {
            "skill_id": r[0],
            "name": r[1],
            "description": r[2],
            "instructions": r[3],
            "tags": json.loads(r[4] or "[]"),
            "dependencies": json.loads(r[5] or "[]"),
            "inject_full": bool(r[6]),
            "status": r[7],
            "version": r[8],
        }
        for r in rows
    }


def _resolve_deps(skill_ids: list[str], all_skills: dict[str, dict]) -> list[str]:
    """Topological resolution: deps come first, no duplicates."""
    resolved: list[str] = []
    seen: set[str] = set()

    def visit(sid: str):
        if sid in seen or sid not in all_skills:
            return
        seen.add(sid)
        for dep in all_skills[sid]["dependencies"]:
            visit(dep)
        resolved.append(sid)

    for sid in skill_ids:
        visit(sid)
    return resolved


def stitch_system_prompt(base_prompt: str, skill_ids: list[str]) -> tuple[str, list[str]]:
    """Return (final system prompt, resolved skill id list) given a base prompt
    and the skill_ids the prompt (or caller) requested."""
    if not skill_ids:
        return base_prompt, []

    all_skills = _fetch_all()
    resolved = _resolve_deps(skill_ids, all_skills)

    blocks = []
    for sid in resolved:
        s = all_skills[sid]
        blocks.append(f"### Skill: {s['name']}\n{s['instructions']}")

    final = base_prompt + "\n\n---\n\n" + "\n\n".join(blocks)
    return final, resolved
