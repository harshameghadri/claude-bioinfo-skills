#!/usr/bin/env bash
# Offline tests for host-pathogen-composite-reference. Needs python3; the STAR test needs STAR (skipped otherwise).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
python3 -I test_composite.py
