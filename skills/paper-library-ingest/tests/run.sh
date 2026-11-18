#!/usr/bin/env bash
# Offline tests for paper-library-ingest. No network, no model. Exit 0 = pass.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
for tool in git python3; do
  command -v "$tool" >/dev/null || { echo "FAIL: $tool not installed" >&2; exit 1; }
done
if ! command -v pdftotext >/dev/null || ! command -v pdfinfo >/dev/null; then
  echo "SKIP: poppler (pdftotext/pdfinfo) not installed; the scan/plan/apply path is untested on this machine"
  exit 0
fi
python3 -I "$here/test_ingest.py"
