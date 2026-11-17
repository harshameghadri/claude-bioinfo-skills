#!/usr/bin/env bash
# Offline test suite for sra-ena-geo-download. Needs python3; end-to-end download tests also need aria2c.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
python3 -I test_sra_dl.py
