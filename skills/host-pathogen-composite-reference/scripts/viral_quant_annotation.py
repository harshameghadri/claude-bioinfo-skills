#!/usr/bin/env python3
"""viral_quant_annotation.py - per-gene GTF for a pathogen/viral contig from an NCBI-style GFF3.

Why: GFF3 files of viral genomes often carry exon rows for only a few genes (the rest are gene + CDS rows).
STAR counts only exon rows, so those genes are silently never quantified. This tool gives EVERY gene a footprint:
    exon rows (directly, or via its mRNA/transcript)  ->  else CDS rows  ->  else the gene row.
Optionally the footprint is extended strand-aware at the 5' end (5' libraries pile reads up in the 5'UTR upstream of the CDS)
or at the 3' end (3' libraries pile reads up in the 3'UTR). Overlaps between neighbouring features are reported before and
after extension. Features that cross the origin of a circular genome are placed explicitly (see --wrap) and listed.

Python port of the R script that built a per-gene EBV quantification annotation (rtracklayer/GenomicRanges); output
columns and GTF layout are kept identical. Standard library only.

Outputs for --out-gtf X.gtf: X.gtf (gene + exon rows), X_genes.tsv (one row per gene), X_overlaps.tsv,
X_wrapped.tsv (only if features crossed the origin). Coordinates are 1-based, extension already applied.

Exit codes: 0 ok, 1 error, 2 usage error.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote

RNA_TYPES = {"mRNA", "transcript", "ncRNA", "lnc_RNA", "misc_RNA", "rRNA", "tRNA", "snRNA", "snoRNA", "primary_transcript", "RNase_P_RNA", "SRP_RNA"}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


class Fail(Exception):
    pass


def fasta_lengths(path: str) -> dict[str, int]:
    import gzip
    opener = gzip.open if path.endswith(".gz") else open
    lens: dict[str, int] = {}
    cur = None
    with opener(path, "rt") as fh:
        for ln in fh:
            if ln.startswith(">"):
                cur = ln[1:].split()[0]
                if cur in lens:
                    raise Fail(f"duplicate contig name in FASTA: {cur}")
                lens[cur] = 0
            elif cur is not None:
                lens[cur] += len(ln.strip())
    return lens


def parse_attrs(s: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for item in s.strip().split(";"):
        if "=" in item:
            k, v = item.split("=", 1)
            out[k] = [unquote(x) for x in v.split(",")]
    return out


def first(d: dict, k: str):
    v = d.get(k)
    return v[0] if v else None


def merge_blocks(blocks: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """IRanges::reduce semantics: merge overlapping and directly adjacent ranges."""
    out: list[list[int]] = []
    for s, e in sorted(blocks):
        if out and s <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def place(start: int, end: int, clen: int, mode: str, wraps: list, label: str, ftype: str) -> list[tuple[int, int]]:
    """Return in-contig blocks for a feature that may cross the origin of a circular contig."""
    if start >= 1 and end <= clen and start <= end:
        return [(start, end)]
    if start > end and end >= 1 and start <= clen:             # written as a wrap: start..L plus 1..end
        raw = [(start, clen), (1, end)]
    elif start > clen:                                         # entirely beyond the end: shift by the contig length
        raw = [(start - clen, end - clen)]
    elif end > clen:                                           # straddles the origin
        raw = [(start, clen), (1, end - clen)] if mode == "split" else [(start, clen)]
    else:
        raise Fail(f"{label} ({ftype}) has coordinates {start}..{end} outside contig length {clen}")
    if mode == "error":
        raise Fail(f"{label} ({ftype}) crosses the contig origin ({start}..{end}, length {clen}); choose --wrap split|cap")
    wraps.append({"feature": label, "type": ftype, "gff_start": start, "gff_end": end, "placed_as": ",".join(f"{a}-{b}" for a, b in raw), "mode": mode})
    return raw


def read_gff(path: str, contig: str):
    rows = []
    hdr_len = None
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            if ln.startswith("##sequence-region"):
                p = ln.split()
                if len(p) >= 4 and p[1] == contig:
                    hdr_len = int(p[3])
            if ln.startswith("#") or not ln.strip():
                continue
            c = ln.rstrip("\n").split("\t")
            if len(c) < 9 or c[0] != contig:
                continue
            rows.append({"type": c[2], "start": int(c[3]), "end": int(c[4]), "strand": c[6], "a": parse_attrs(c[8])})
    return rows, hdr_len


def build(args):
    rows, hdr_len = read_gff(args.gff, args.contig)
    if not rows:
        raise Fail(f"no GFF3 rows on contig {args.contig}")
    if args.contig_length:
        clen = args.contig_length
    elif args.fasta:
        lens = fasta_lengths(args.fasta)
        if args.contig not in lens:
            raise Fail(f"contig {args.contig} not in {args.fasta}")
        clen = lens[args.contig]
    elif hdr_len:
        clen = hdr_len
    else:
        clen = max(max(r["start"], r["end"]) for r in rows)
        log(f"WARNING: contig length unknown; using the largest coordinate ({clen}). Pass --fasta or --contig-length.")
    wraps: list[dict] = []

    genes, rnas = [], []
    for r in rows:
        a = r["a"]
        r["ID"], r["Parent"], r["Name"] = first(a, "ID"), first(a, "Parent"), first(a, "Name")
        r["locus_tag"], r["product"] = first(a, "locus_tag"), first(a, "product")
        r["biotype"] = first(a, "gene_biotype")
        r["dbx"] = a.get("Dbxref", [])
        if r["type"] == "gene":
            genes.append(r)
        elif r["type"] in RNA_TYPES:
            rnas.append(r)
    # orphan transcripts (no parent gene, e.g. small viral RNAs) become pseudo-genes named from the product string
    gene_ids_by_ID = {g["ID"] for g in genes if g["ID"]}
    orphans = [t for t in rnas if (t["Parent"] is None or t["Parent"] not in gene_ids_by_ID) and re.search(args.orphan_name_regex, t["product"] or t["Name"] or "")]
    orphan_rna_ids = {t["ID"] for t in orphans}
    for t in orphans:
        nm = re.sub(rf"^({args.orphan_name_regex}).*", r"\1", t["product"] or t["Name"])
        genes.append({"type": "gene", "ID": t["ID"], "Parent": None, "Name": nm, "locus_tag": nm, "product": t["product"], "biotype": t["biotype"] or "misc_RNA",
                      "dbx": [], "start": t["start"], "end": t["end"], "strand": t["strand"], "a": {}})
    for g in genes:
        gid = g["locus_tag"] or g["Name"] or g["ID"]
        if args.strip_prefix and gid and gid.startswith(args.strip_prefix):
            gid = gid[len(args.strip_prefix):]
        g["gene_id"] = gid
        g["gene_name"] = g["Name"] or first(g["a"], "gene") or gid
        g["biotype"] = g["biotype"] or "unknown"
        m = next((re.search(r"GeneID:([0-9]+)", d) for d in g["dbx"] if "GeneID:" in d), None)
        g["ncbi_geneid"] = m.group(1) if m else "NA"
    ids = [g["gene_id"] for g in genes]
    if any(i is None for i in ids):
        raise Fail("gene without locus_tag/Name/ID")
    dups = sorted({i for i in ids if ids.count(i) > 1})
    if dups:
        raise Fail(f"gene_id not unique (choose a different attribute or fix the GFF3): {dups[:10]}")

    gene_by_ID = {g["ID"]: g for g in genes if g["ID"]}
    rna2gene = {t["ID"]: t["Parent"] for t in rnas if t["ID"]}
    for oid in orphan_rna_ids:
        rna2gene[oid] = oid
    parts: dict[str, dict[str, list[tuple[int, int]]]] = {}
    for r in rows:
        if r["type"] not in ("exon", "CDS"):
            continue
        owner = r["Parent"] if r["Parent"] in gene_by_ID else rna2gene.get(r["Parent"])
        if owner not in gene_by_ID:
            continue
        gid = gene_by_ID[owner]["gene_id"]
        lab = f"{gid}:{r['type']}"
        parts.setdefault(gid, {}).setdefault(r["type"], []).extend(place(r["start"], r["end"], clen, args.wrap, wraps, lab, r["type"]))

    blocks, src = {}, {}
    for g in genes:
        gid = g["gene_id"]
        p = parts.get(gid, {})
        if p.get("exon"):
            blocks[gid], src[gid] = merge_blocks(p["exon"]), "exon"
        elif p.get("CDS"):
            blocks[gid], src[gid] = merge_blocks(p["CDS"]), "CDS"
        else:
            blocks[gid], src[gid] = merge_blocks(place(g["start"], g["end"], clen, args.wrap, wraps, f"{gid}:gene", "gene")), "gene"
    strand = {g["gene_id"]: g["strand"] for g in genes}
    name = {g["gene_id"]: g["gene_name"] for g in genes}

    def ext5(bl, st, e):
        bl = list(bl)
        if st == "+":
            bl[0] = (max(1, bl[0][0] - e), bl[0][1])
        else:
            bl[-1] = (bl[-1][0], min(clen, bl[-1][1] + e))
        return bl

    def ext3(bl, st, e):
        bl = list(bl)
        if st == "+":
            bl[-1] = (bl[-1][0], min(clen, bl[-1][1] + e))
        else:
            bl[0] = (max(1, bl[0][0] - e), bl[0][1])
        return bl

    applies = lambda gid, e: e > 0 and (args.ext_for == "all" or src[gid] != "exon")
    ext_blocks = {}
    for gid, bl in blocks.items():
        nb = ext5(bl, strand[gid], args.upstream_ext) if applies(gid, args.upstream_ext) else bl
        if applies(gid, args.downstream_ext):
            nb = ext3(nb, strand[gid], args.downstream_ext)
        ext_blocks[gid] = nb

    def pair_bp(bl_by_gene):
        flat = sorted((s, e, gid) for gid, bl in bl_by_gene.items() for s, e in bl)
        agg: dict[tuple[str, str], int] = {}
        for i, (s1, e1, g1) in enumerate(flat):
            for s2, e2, g2 in flat[i + 1:]:
                if s2 > e1:
                    break
                if g1 == g2:
                    continue
                w = min(e1, e2) - max(s1, s2) + 1
                if w > 0:
                    k = (g1, g2) if g1 < g2 else (g2, g1)
                    agg[k] = agg.get(k, 0) + w
        return agg

    span = lambda bl_by_gene: {g: [(min(s for s, _ in bl), max(e for _, e in bl))] for g, bl in bl_by_gene.items()}
    ov0, ov1, ovs = pair_bp(blocks), pair_bp(ext_blocks), pair_bp(span(ext_blocks))
    pairs = sorted(set(ov0) | set(ov1))
    ovl = []
    for a, b in pairs:
        before, after = ov0.get((a, b), 0), ov1.get((a, b), 0)
        ovl.append({"id_a": a, "id_b": b, "name_a": name[a], "name_b": name[b], "strand_a": strand[a], "strand_b": strand[b],
                    "same_strand": strand[a] == strand[b], "same_name": name[a] == name[b], "exon_overlap_bp_before": before,
                    "exon_overlap_bp_after": after, "span_overlap_bp_after": ovs.get((a, b), 0), "new_after_extension": before == 0 and after > 0})
    for a, b in sorted(k for k in ovs if k not in set(pairs)):
        ovl.append({"id_a": a, "id_b": b, "name_a": name[a], "name_b": name[b], "strand_a": strand[a], "strand_b": strand[b],
                    "same_strand": strand[a] == strand[b], "same_name": name[a] == name[b], "exon_overlap_bp_before": 0,
                    "exon_overlap_bp_after": 0, "span_overlap_bp_after": ovs[(a, b)], "new_after_extension": False})
    ss = lambda o: o["same_strand"] and not o["same_name"]

    star_ids: set[str] = set()
    if args.composite_gtf and Path(args.composite_gtf).is_file():
        for ln in open(args.composite_gtf):
            c = ln.split("\t")
            if len(c) > 8 and c[0] == args.contig and c[2] == "exon":
                m = re.search(r'gene_id "([^"]+)"', c[8])
                if m:
                    star_ids.add(m.group(1))
    tab = []
    for g in genes:
        gid = g["gene_id"]
        b0, be = blocks[gid], ext_blocks[gid]
        inv = [o for o in ovl if gid in (o["id_a"], o["id_b"])]
        other = lambda o: o["id_b"] if o["id_a"] == gid else o["id_a"]
        row = {"gene_id": gid, "gene_name": name[gid], "strand": strand[gid], "biotype": g["biotype"], "ncbi_geneid": g["ncbi_geneid"],
               "source": src[gid], "n_blocks": len(b0), "footprint_start": min(s for s, _ in b0), "footprint_end": max(e for _, e in b0),
               "ext_applied_bp": args.upstream_ext if applies(gid, args.upstream_ext) else 0,
               "start_ext": min(s for s, _ in be), "end_ext": max(e for _, e in be), "footprint_bp_ext": sum(e - s + 1 for s, e in be),
               "in_star_composite": ("NA" if not star_ids else ("TRUE" if (name[gid] in star_ids or gid in star_ids) else "FALSE"))}
        if args.downstream_ext > 0:
            row["ext3p_applied_bp"] = args.downstream_ext if applies(gid, args.downstream_ext) else 0
        row["n_same_strand_overlaps_before"] = sum(1 for o in inv if ss(o) and o["exon_overlap_bp_before"] > 0)
        row["n_same_strand_overlaps_after"] = sum(1 for o in inv if ss(o) and o["exon_overlap_bp_after"] > 0)
        join = lambda sel: ";".join(sorted({other(o) for o in inv if sel(o)}))
        row["same_strand_overlap_ids_after"] = join(lambda o: ss(o) and o["exon_overlap_bp_after"] > 0)
        row["new_overlap_ids_after_ext"] = join(lambda o: ss(o) and o["new_after_extension"])
        row["antisense_overlap_ids_after"] = join(lambda o: not o["same_strand"] and not o["same_name"] and o["exon_overlap_bp_after"] > 0)
        row["same_name_other_loci"] = ";".join(x["gene_id"] for x in genes if x["gene_name"] == name[gid] and x["gene_id"] != gid)
        tab.append(row)
    tab.sort(key=lambda r: (r["footprint_start"], r["gene_id"]))

    lines = []
    for r in tab:
        gid, st = r["gene_id"], r["strand"]
        bl = sorted(ext_blocks[gid], key=lambda x: x[0], reverse=(st == "-"))
        attr = f'gene_id "{gid}"; transcript_id "{gid}"; gene_name "{name[gid]}"; gene_biotype "{r["biotype"]}"; feature_source "{src[gid]}"; ext_5p "{r["ext_applied_bp"]}";'
        if args.downstream_ext > 0:
            attr += f' ext_3p "{r["ext3p_applied_bp"]}";'
        lines.append(f"{args.contig}\t{args.gtf_source}\tgene\t{min(s for s, _ in bl)}\t{max(e for _, e in bl)}\t.\t{st}\t.\t{attr}")
        lines += [f"{args.contig}\t{args.gtf_source}\texon\t{s}\t{e}\t.\t{st}\t.\t{attr}" for s, e in bl]
    return tab, ovl, lines, wraps, src, clen


def write_tsv(path, rows, cols=None):
    cols = cols or (list(rows[0].keys()) if rows else [])
    with open(path, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in rows:
            fh.write("\t".join(str(r[c]).upper() if isinstance(r[c], bool) else str(r[c]) for c in cols) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gff", required=True, help="GFF3 of the pathogen genome")
    ap.add_argument("--contig", required=True, help="contig/seqid name in the GFF3 and the composite FASTA, e.g. NC_007605.1")
    ap.add_argument("--out-gtf", required=True)
    ap.add_argument("--fasta", help="FASTA that contains the contig (length source; .gz ok)")
    ap.add_argument("--contig-length", type=int, help="contig length in bp (alternative to --fasta)")
    ap.add_argument("--composite-gtf", help="existing composite GTF, only to flag genes already quantified by STAR")
    ap.add_argument("--upstream-ext", type=int, default=0, help="strand-aware 5' extension in bp (default 0; starter value for 5' libraries: 300, NOT validated)")
    ap.add_argument("--downstream-ext", type=int, default=0, help="strand-aware 3' extension in bp for 3' libraries (default 0)")
    ap.add_argument("--ext-for", choices=["cds_only", "all"], default="cds_only", help="extend only features without exon structure (default) or all")
    ap.add_argument("--wrap", choices=["split", "cap", "error"], default="split",
                    help="features crossing the circular origin: split = two blocks (default); cap = truncate at the contig end; error = stop")
    ap.add_argument("--strip-prefix", default="", help="prefix removed from locus_tag to make gene_id, e.g. HHV4_")
    ap.add_argument("--orphan-name-regex", default=r"EBER-[12]|[A-Za-z0-9]+-?RNA[0-9]*", help="transcripts without a gene row are promoted to pseudo-genes when product/Name matches")
    ap.add_argument("--gtf-source", default="viral_quant", help="GTF source column")
    ap.add_argument("--overwrite", action="store_true")
    try:
        args = ap.parse_args(argv)
        if args.upstream_ext < 0 or args.downstream_ext < 0:
            raise Fail("extensions must be >= 0")
        out = Path(args.out_gtf)
        tabp, ovp, wrp = (str(out.with_suffix("")) + s for s in ("_genes.tsv", "_overlaps.tsv", "_wrapped.tsv"))
        if not args.overwrite and any(Path(p).exists() for p in (str(out), tabp, ovp)):
            raise Fail(f"output exists (use --overwrite): {out}")
        out.parent.mkdir(parents=True, exist_ok=True)
        tab, ovl, lines, wraps, src, clen = build(args)
        out.write_text("\n".join(lines) + "\n")
        write_tsv(tabp, tab)
        write_tsv(ovp, ovl, ["id_a", "id_b", "name_a", "name_b", "strand_a", "strand_b", "same_strand", "same_name", "exon_overlap_bp_before",
                             "exon_overlap_bp_after", "span_overlap_bp_after", "new_after_extension"])
        if wraps:
            write_tsv(wrp, wraps)
            log(f"{len(wraps)} feature(s) crossed the contig origin (mode {args.wrap}); inspect {wrp}")
        n = {k: sum(1 for v in src.values() if v == k) for k in ("exon", "CDS", "gene")}
        log(f"contig {args.contig} length {clen}; features: {len(tab)} (exon-defined {n['exon']}, CDS-defined {n['CDS']}, gene-row only {n['gene']})")
        newp = [r for r in tab if r["new_overlap_ids_after_ext"]]
        if newp:
            log("features that overlap a same-strand neighbour ONLY after extension: " + ", ".join(f"{r['gene_id']}<->{r['new_overlap_ids_after_ext']}" for r in newp))
        log(f"wrote {out}, {tabp}, {ovp}")
        return 0
    except Fail as e:
        log(f"error: {e}")
        return 1
    except SystemExit as e:
        return int(e.code or 0)


if __name__ == "__main__":
    sys.exit(main())
