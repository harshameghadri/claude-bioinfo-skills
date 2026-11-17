#!/usr/bin/env bash
# Offline tests for dataset-audit (python3, standard library only).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"
python3 -I -W error::ResourceWarning -m unittest discover -s "$here" -p 'test_*.py' 2>&1 | tail -n 40
test "${PIPESTATUS[0]}" -eq 0
