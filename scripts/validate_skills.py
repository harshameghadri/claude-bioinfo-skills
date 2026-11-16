#!/usr/bin/env python3
"""Check every skills/*/SKILL.md: frontmatter present, name == folder, description non-empty."""
import re, sys, pathlib

root = pathlib.Path(__file__).resolve().parent.parent / "skills"
errors = []
for skill_md in sorted(root.glob("*/SKILL.md")):
    folder = skill_md.parent.name
    text = skill_md.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        errors.append(f"{folder}: missing YAML frontmatter"); continue
    fm = m.group(1)
    name = re.search(r"^name:\s*(\S+)\s*$", fm, re.M)
    desc = re.search(r"^description:\s*(.+)$", fm, re.M | re.S)
    if not name or name.group(1) != folder:
        errors.append(f"{folder}: 'name' must equal folder name")
    if not desc or not desc.group(1).strip():
        errors.append(f"{folder}: empty description")
    if re.search(r"authoring_session|published_by", fm):
        errors.append(f"{folder}: session metadata should be stripped before publishing")
if errors:
    print("\n".join(errors)); sys.exit(1)
print(f"OK: {len(list(root.glob('*/SKILL.md')))} skills validated")
