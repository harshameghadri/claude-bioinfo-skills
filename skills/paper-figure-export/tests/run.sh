#!/usr/bin/env bash
# Offline tests for paper-figure-export. Needs python3; R tests need Rscript with ggplot2 + systemfonts (skipped otherwise).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"
python3 -I -m unittest discover -s "$here" -p 'test_*.py' -v 2>&1 | tail -n 60
test "${PIPESTATUS[0]}" -eq 0
