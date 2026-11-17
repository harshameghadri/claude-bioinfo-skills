#!/usr/bin/env bash
# Offline tests for parse-vs-10x-qc (synthetic matrices; needs R with Matrix, data.table, VGAM).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
command -v Rscript >/dev/null || { echo "Rscript not found" >&2; exit 1; }
Rscript -e 'for (p in c("Matrix","data.table","VGAM")) if (!requireNamespace(p, quietly=TRUE)) { cat("missing R package:", p, "\n", file=stderr()); quit(status=1) }'
Rscript "$here/run_tests.R"
