#!/usr/bin/env bash
# Rebuild catalog + HTML, then commit everything with an informative message.
# Usage: commit.sh [--root DIR] "short reason"     (run from <library>/tools/ or with --root)
# Exit codes: 0 ok (or nothing to commit), 2 not a library, other = failure of a step.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$here/.."
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then sed -n '2,5p' "$0"; exit 0; fi
if [ "${1:-}" = "--root" ]; then root="$2"; shift 2; fi
cd "$root"
[ -f _meta/papers.jsonl ] || { echo "not a library (no _meta/papers.jsonl); use --root DIR" >&2; exit 2; }
tmp="$(mktemp)"
python3 "$here/catalog.py" --root "$PWD" | tee "$tmp"
python3 "$here/build_html.py" --root "$PWD"
git add -A
if git diff --cached --quiet; then echo "nothing to commit"; rm -f "$tmp"; exit 0; fi
git commit -q -m "${1:-library update} | $(head -1 "$tmp")" && git log --oneline -1
rm -f "$tmp"
