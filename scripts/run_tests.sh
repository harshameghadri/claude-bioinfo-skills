#!/usr/bin/env bash
# Run the offline tests of every skill (skills/*/tests/run.sh) and summarise. Usage: scripts/run_tests.sh [skill-name ...]
set -u
root="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$#" -gt 0 ]; then skills=("$@"); else skills=(); for d in "$root"/skills/*/; do skills+=("$(basename "$d")"); done; fi
pass=(); fail=(); none=()
for s in "${skills[@]}"; do
  t="$root/skills/$s/tests/run.sh"
  if [ ! -f "$t" ]; then none+=("$s"); continue; fi
  echo "=== $s"
  if bash "$t"; then pass+=("$s"); else fail+=("$s"); fi
done
echo
echo "passed: ${pass[*]:-none}"
echo "no tests: ${none[*]:-none}"
echo "failed: ${fail[*]:-none}"
[ "${#fail[@]}" -eq 0 ]
