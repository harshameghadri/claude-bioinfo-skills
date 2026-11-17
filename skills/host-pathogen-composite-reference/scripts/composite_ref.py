#!/usr/bin/env python3
"""composite_ref.py - build and check a host + pathogen composite reference for STAR/STARsolo.

  build        merge host and pathogen FASTA/GTF into one composite FASTA/GTF (streaming, .gz inputs ok)
  check        validate a composite FASTA/GTF pair before an expensive index build
  star-params  compute STAR index parameters (genomeSAindexNbases, sjdbOverhang) and print the genomeGenerate command

Why a separate check: errors in a composite reference surface hours later (index build failure) or never
(reads from genes without exon rows are silently not counted). Standard library only (Python >= 3.8).

Exit codes: 0 ok, 1 errors found, 2 usage error. `check --strict` also fails on warnings.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import sys
from pathlib import Path


def log(*a):
    print(*a, file=sys.stderr, flush=True)


class Fail(Exception):
    pass


def opener(path: str):
    return (lambda p: gzip.open(p, "rt")) if str(path).endswith(".gz") else (lambda p: open(p, "r"))


def contig_name(header_line: str) -> str:
    return header_line[1:].strip().split()[0] if len(header_line) > 1 else ""


def copy_fasta(src: str, out_fh, lens: dict, origin: dict, label: str) -> None:
    cur = None
    last_char = "\n"
    with opener(src)(src) as fh:
        for ln in fh:
            if ln.startswith(">"):
                if not last_char.endswith("\n"):
                    out_fh.write("\n")
                cur = contig_name(ln)
                if not cur:
                    raise Fail(f"{src}: empty contig name in header {ln!r}")
                if cur in lens:
                    raise Fail(f"duplicate contig name {cur!r}: present in {origin[cur]} and {label}. Rename one before merging.")
                lens[cur], origin[cur] = 0, label
            elif cur is None:
                if ln.strip():
                    raise Fail(f"{src}: sequence before the first FASTA header")
                continue
            else:
                lens[cur] += len(ln.strip())
            out_fh.write(ln if ln.endswith("\n") else ln + "\n")
            last_char = "\n"
    if cur is None:
        raise Fail(f"{src}: no FASTA records")


def cmd_build(a) -> int:
    lens: dict[str, int] = {}
    origin: dict[str, str] = {}
    Path(a.out_fasta).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out_fasta, "w") as out:
        copy_fasta(a.host_fasta, out, lens, origin, "host")
        n_host = len(lens)
        copy_fasta(a.virus_fasta, out, lens, origin, "pathogen")
    virus_contigs = [c for c, o in origin.items() if o == "pathogen"]
    n_gtf = {"host": 0, "pathogen": 0}
    gene_ids: dict[str, str] = {}
    with open(a.out_gtf, "w") as out:
        for label, path in (("host", a.host_gtf), ("pathogen", a.virus_gtf)):
            with opener(path)(path) as fh:
                for ln in fh:
                    if ln.startswith("#") or not ln.strip():
                        if label == "host":
                            out.write(ln if ln.endswith("\n") else ln + "\n")
                        continue
                    c = ln.rstrip("\n").split("\t")
                    if len(c) < 9:
                        raise Fail(f"{path}: line with fewer than 9 tab-separated columns: {ln[:80]!r}")
                    if label == "pathogen" and c[0] not in virus_contigs:
                        raise Fail(f"{path}: contig {c[0]!r} is not in the pathogen FASTA ({virus_contigs})")
                    if label == "host" and c[0] in virus_contigs:
                        raise Fail(f"{path}: host GTF uses pathogen contig name {c[0]!r}")
                    if c[2] == "gene":
                        m = re.search(r'gene_id "([^"]+)"', c[8])
                        if m:
                            if m.group(1) in gene_ids and gene_ids[m.group(1)] != label:
                                raise Fail(f"gene_id {m.group(1)!r} exists in both host and pathogen annotation; rename the pathogen gene_id")
                            gene_ids[m.group(1)] = label
                    out.write(ln if ln.endswith("\n") else ln + "\n")
                    n_gtf[label] += 1
    total = sum(lens.values())
    with open(str(a.out_fasta) + ".contigs.tsv", "w") as fh:
        fh.write("contig\tlength\torigin\n")
        for c, n in lens.items():
            fh.write(f"{c}\t{n}\t{origin[c]}\n")
    log(f"composite FASTA: {len(lens)} contigs ({n_host} host, {len(virus_contigs)} pathogen), {total:,} bp -> {a.out_fasta}")
    log(f"composite GTF: {n_gtf['host']:,} host rows + {n_gtf['pathogen']:,} pathogen rows -> {a.out_gtf}")
    log("next: composite_ref.py check, then composite_ref.py star-params")
    return 0


def read_contig_lengths(fasta: str) -> dict[str, int]:
    lens: dict[str, int] = {}
    cur = None
    with opener(fasta)(fasta) as fh:
        for ln in fh:
            if ln.startswith(">"):
                cur = contig_name(ln)
                if cur in lens:
                    raise Fail(f"duplicate contig name in FASTA: {cur}")
                lens[cur] = 0
            elif cur is not None:
                lens[cur] += len(ln.strip())
    return lens


def cmd_check(a) -> int:
    lens = read_contig_lengths(a.fasta)
    errors: dict[str, list[str]] = {}
    warns: dict[str, list[str]] = {}
    gene_rows: dict[str, str] = {}
    exon_genes: set[str] = set()
    tx_of: dict[str, set[str]] = {}
    n = 0
    with opener(a.gtf)(a.gtf) as fh:
        for i, ln in enumerate(fh, 1):
            if ln.startswith("#") or not ln.strip():
                continue
            c = ln.rstrip("\n").split("\t")
            if len(c) < 9:
                errors.setdefault("fewer than 9 columns", []).append(f"line {i}")
                continue
            n += 1
            chrom, feat = c[0], c[2]
            try:
                s, e = int(c[3]), int(c[4])
            except ValueError:
                errors.setdefault("non-integer coordinates", []).append(f"line {i}")
                continue
            if chrom not in lens:
                errors.setdefault("GTF contig absent from FASTA", []).append(f"{chrom} (line {i})")
                continue
            if s < 1 or e > lens[chrom] or s > e:
                errors.setdefault("coordinates outside contig (or start > end)", []).append(f"{chrom}:{s}-{e} len {lens[chrom]} (line {i}, {feat})")
            if c[6] not in "+-.":
                errors.setdefault("invalid strand", []).append(f"line {i}")
            gm = re.search(r'gene_id "([^"]+)"', c[8])
            tm = re.search(r'transcript_id "([^"]+)"', c[8])
            if feat in ("exon", "CDS") and (not gm or not tm):
                errors.setdefault("exon/CDS row without gene_id or transcript_id (STAR rejects or drops it)", []).append(f"line {i}")
            if gm and feat == "gene":
                gene_rows[gm.group(1)] = chrom
            if gm and feat == "exon":
                exon_genes.add(gm.group(1))
            if gm and tm and feat == "exon":
                tx_of.setdefault(tm.group(1), set()).add(gm.group(1))
    pc = set(a.pathogen_contig or [])
    for c in pc:
        if c not in lens:
            errors.setdefault("--pathogen-contig absent from FASTA", []).append(c)
    no_exon = sorted(g for g, c in gene_rows.items() if g not in exon_genes and (not pc or c in pc))
    if no_exon:
        warns.setdefault("genes with a gene row but no exon rows (never counted by STAR/STARsolo; fix with viral_quant_annotation.py)", []).extend(no_exon)
    multi = sorted(t for t, g in tx_of.items() if len(g) > 1)
    if multi:
        errors.setdefault("transcript_id shared by several gene_ids", []).extend(multi)
    for c, n_ in lens.items():
        if n_ == 0:
            errors.setdefault("empty contig", []).append(c)
    total = sum(lens.values())
    print(f"contigs: {len(lens)}  bases: {total:,}  GTF feature rows: {n:,}  genes with exon rows: {len(exon_genes):,}")
    for title, d in (("ERROR", errors), ("WARNING", warns)):
        for k, v in d.items():
            sample = ", ".join(v[:8]) + (f" ... (+{len(v) - 8} more)" if len(v) > 8 else "")
            print(f"{title}: {k}: {len(v)}: {sample}")
    if not errors and not warns:
        print("OK: no problems found")
    return 1 if errors or (a.strict and warns) else 0


def sa_index_nbases(genome_len: int) -> int:
    """STAR manual: min(14, log2(GenomeLength)/2 - 1). Depends on the TOTAL genome length."""
    return max(4, min(14, int(math.floor(math.log2(max(genome_len, 2)) / 2 - 1))))


def cmd_star_params(a) -> int:
    if a.genome_length:
        total = a.genome_length
    elif a.fasta:
        total = sum(read_contig_lengths(a.fasta).values())
    else:
        raise Fail("give --fasta or --genome-length")
    sa = sa_index_nbases(total)
    ovh = (a.read_length - 1) if a.read_length else 100
    info = {"genome_length": total, "genomeSAindexNbases": sa, "sjdbOverhang": ovh,
            "note": "genomeSAindexNbases follows the total genome length, not the smallest contig; a human+virus composite stays at 14"}
    if a.json:
        print(json.dumps(info, indent=2))
        return 0
    ram = a.limit_ram_gb
    print("STAR --runMode genomeGenerate \\\n"
          f"  --runThreadN {a.threads} \\\n  --genomeDir INDEX_DIR \\\n  --genomeFastaFiles {a.fasta or 'COMPOSITE.fa'} \\\n"
          f"  --sjdbGTFfile {a.gtf or 'COMPOSITE.gtf'} \\\n  --sjdbOverhang {ovh} \\\n  --genomeSAindexNbases {sa}"
          + (f" \\\n  --limitGenomeGenerateRAM {int(ram * 1e9)}" if ram else ""))
    log(f"genome length {total:,} -> genomeSAindexNbases {sa}; sjdbOverhang {ovh} ({'read length - 1' if a.read_length else 'STAR default; set --read-length'})")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build", help="merge host + pathogen FASTA/GTF")
    p.add_argument("--host-fasta", required=True); p.add_argument("--host-gtf", required=True)
    p.add_argument("--virus-fasta", required=True); p.add_argument("--virus-gtf", required=True)
    p.add_argument("--out-fasta", required=True); p.add_argument("--out-gtf", required=True)
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("check", help="validate a composite FASTA/GTF pair")
    p.add_argument("--fasta", required=True); p.add_argument("--gtf", required=True)
    p.add_argument("--pathogen-contig", nargs="*", help="contig name(s) of the pathogen (limits the no-exon-rows warning to them)")
    p.add_argument("--strict", action="store_true", help="treat warnings as failures")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("star-params", help="STAR index parameters and command")
    p.add_argument("--fasta"); p.add_argument("--gtf"); p.add_argument("--genome-length", type=int)
    p.add_argument("--read-length", type=int, help="longest read of the experiment (cDNA read for 10x); sjdbOverhang = length - 1")
    p.add_argument("--threads", type=int, default=16); p.add_argument("--limit-ram-gb", type=float)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_star_params)
    try:
        a = ap.parse_args(argv)
        return a.fn(a)
    except Fail as e:
        log(f"error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
