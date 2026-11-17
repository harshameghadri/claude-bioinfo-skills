#!/usr/bin/env python3
"""whitelist_preflight.py - check that a library's cell barcodes belong to the barcode whitelist you are about to use.

Reads the first N reads of the barcode read (R1) of a 10x-style library, takes the cell barcode (default bases 1-16)
and reports the fraction found exactly in the whitelist, plus the reverse-complement fraction as a diagnostic.

Why: using the wrong whitelist (chemistry v2 vs v3 vs GEM-X vs Multiome) does not crash STARsolo; it silently returns
a tiny fraction of 'valid barcodes' and a few hundred 'cells'. In one real case the valid-barcode fraction was 0.018
against 0.71-0.96 for correctly configured libraries; a 100k-read pre-flight shows this in seconds.

Exit codes: 0 hit rate >= --min-hit, 1 error, 2 usage error, 3 hit rate below --min-hit.
"""
from __future__ import annotations

import argparse
import gzip
import sys


def opener(p):
    return gzip.open(p, "rt") if str(p).endswith(".gz") else open(p, "r")


def revcomp(s: str) -> str:
    return s.translate(str.maketrans("ACGTN", "TGCAN"))[::-1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--r1", required=True, help="barcode read FASTQ(.gz)")
    ap.add_argument("--whitelist", nargs="+", required=True, help="one or more whitelist files (.gz ok); several are compared")
    ap.add_argument("--reads", type=int, default=100000)
    ap.add_argument("--cb-start", type=int, default=1, help="1-based start of the cell barcode in R1 (default 1)")
    ap.add_argument("--cb-len", type=int, default=16)
    ap.add_argument("--min-hit", type=float, default=0.90, help="required exact-match fraction for the FIRST whitelist (default 0.90)")
    a = ap.parse_args(argv)
    try:
        bcs = []
        with opener(a.r1) as fh:
            for i, ln in enumerate(fh):
                if i % 4 == 1:
                    bcs.append(ln.strip()[a.cb_start - 1:a.cb_start - 1 + a.cb_len])
                    if len(bcs) >= a.reads:
                        break
        if not bcs:
            print("error: no reads", file=sys.stderr)
            return 1
        rates = []
        for w in a.whitelist:
            with opener(w) as fh:
                wl = {x.strip() for x in fh if x.strip()}
            hit = sum(b in wl for b in bcs) / len(bcs)
            rc = sum(revcomp(b) in wl for b in bcs) / len(bcs)
            rates.append(hit)
            print(f"{w}\tbarcodes={len(wl)}\treads={len(bcs)}\texact_hit={hit:.4f}\trevcomp_hit={rc:.4f}")
        best = max(range(len(rates)), key=lambda i: rates[i])
        if len(a.whitelist) > 1:
            print(f"best match: {a.whitelist[best]}")
        if rates[0] < a.min_hit:
            print(f"FAIL: exact hit rate {rates[0]:.4f} < {a.min_hit} for {a.whitelist[0]}: wrong chemistry/whitelist, wrong --cb-start, or barcode read is not R1", file=sys.stderr)
            return 3
        return 0
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
