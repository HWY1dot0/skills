#!/usr/bin/env python3
"""
inventory_skills.py — Inventory the skills under a directory tree.

Scans for SKILL.md files, extracts the `name` and `description` from each
skill's YAML frontmatter, and prints an inventory. Use this on:
  - the environment's local skill directories,
  - a registry repo you've cloned/downloaded into a sandbox for inspection.

It turns "go look at the skills" into a concrete, scannable candidate list —
the raw material for the scoring step. It does NOT judge or run anything; that's
Steps 3–5 of the skill-selector workflow.

Usage:
    python inventory_skills.py <directory> [--json]

Examples:
    python inventory_skills.py /path/to/skills
    python inventory_skills.py ./cloned-registry --json > candidates.json
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
SKIP_DIRS = {"__pycache__", "node_modules", ".git"}


def _walk_skill_mds(root: Path):
    """os.walk(followlinks=True) — rglob does NOT follow directory symlinks, so a
    symlinked skill install (dotfiles-style) silently vanishes from the inventory."""
    seen: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        rp = os.path.realpath(dirpath)
        if rp in seen:  # symlink loop guard
            dirnames[:] = []
            continue
        seen.add(rp)
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if "SKILL.md" in filenames:
            yield Path(dirpath) / "SKILL.md"


def _parse_frontmatter(text: str) -> dict:
    """Return {name, description} from a SKILL.md's frontmatter.

    Prefers a real YAML parse; falls back to line-regex if PyYAML is missing
    or the YAML is malformed, so the script works in minimal environments.
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    block = m.group(1)

    try:
        import yaml  # type: ignore

        data = yaml.safe_load(block)
        if isinstance(data, dict):
            return {
                "name": str(data.get("name", "")).strip(),
                "description": str(data.get("description", "")).strip(),
            }
    except Exception:
        pass

    # Fallback: grab the first `name:` and `description:` lines.
    out = {"name": "", "description": ""}
    for key in ("name", "description"):
        km = re.search(rf"^{key}\s*:\s*(.+)$", block, re.MULTILINE)
        if km:
            out[key] = km.group(1).strip().strip("\"'")
    return out


def inventory(root: Path) -> list[dict]:
    skills = []
    for skill_md in sorted(_walk_skill_mds(root)):
        try:
            fm = _parse_frontmatter(skill_md.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:  # pragma: no cover - unreadable file
            fm = {"name": "", "description": f"<unreadable: {e}>"}
        skills.append(
            {
                "name": fm.get("name") or skill_md.parent.name,
                "description": fm.get("description", ""),
                "path": str(skill_md.parent),
            }
        )
    skills.sort(key=lambda s: s["name"].lower())
    return skills


def main() -> int:
    ap = argparse.ArgumentParser(description="Inventory skills under a directory.")
    ap.add_argument("directory", help="Directory to scan for SKILL.md files")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    args = ap.parse_args()

    root = Path(args.directory).expanduser()
    if not root.exists():
        print(f"error: no such directory: {root}", file=sys.stderr)
        return 1

    skills = inventory(root)

    if args.json:
        print(json.dumps(skills, indent=2, ensure_ascii=False))
        return 0

    if not skills:
        print(f"No SKILL.md files found under {root}")
        return 0

    print(f"Found {len(skills)} skill(s) under {root}:\n")
    width = max(len(s["name"]) for s in skills)
    for s in skills:
        desc = s["description"].replace("\n", " ")
        if len(desc) > 100:
            desc = desc[:97] + "..."
        print(f"  {s['name']:<{width}}  {desc}")
        print(f"  {'':<{width}}  ↳ {s['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
