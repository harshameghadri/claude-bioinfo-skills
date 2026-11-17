#!/usr/bin/env python3
"""dataset_audit.py - integrity and design audit of a sequencing dataset BEFORE analysis. Standard library only.

Subcommands
  inventory    files in a directory: zero-byte, incomplete downloads (.aria2/.part/.tmp), gzip integrity, optional md5 vs expectations
  fastq        FASTQ structure, mate pairing, read counts and read-name agreement between mates
  matrix       10x / Parse count-matrix directory: dimensions vs annotation, orientation, integer counts, ids, duplicates, empty cells
  samplesheet  sample sheet vs files on disk: missing, orphan, duplicated, blank or space-containing entries
  design       metadata table: replicates per group, perfectly confounded factors, pseudo-replication

Every check prints one tab-separated line to stdout:  SEVERITY  check  subject  detail   (SEVERITY: ERROR, WARN, INFO, OK)
A summary goes to stderr. Exit codes: 0 no ERROR (and no WARN with --strict), 1 internal error, 2 usage, 4 findings at or above the failing level.
"""
import argparse, csv, gzip, hashlib, io, os, re, struct, sys, zlib
from collections import Counter, defaultdict

SEV = {"OK": 0, "INFO": 0, "WARN": 1, "ERROR": 2}
findings = []


def report(sev, check, subject, detail=""):
    findings.append(sev)
    print("\t".join([sev, check, str(subject), str(detail)]))


def opener(path):
    return gzip.open(path, "rt", newline="") if path.endswith(".gz") else open(path, "rt", newline="")


def md5_file(path, chunk=1 << 20):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- inventory
INCOMPLETE = (".aria2", ".part", ".tmp", ".crdownload", ".download")


def gz_ok(path, mode):
    if mode == "none":
        return True, ""
    try:
        with gzip.open(path, "rb") as fh:
            if mode == "head":
                fh.read(1 << 20)
            else:
                while fh.read(1 << 22):
                    pass
        return True, ""
    except (OSError, EOFError, zlib.error) as e:
        return False, str(e)


def load_expected(args):
    exp = {}
    if args.md5_list:
        with open(args.md5_list) as fh:
            for line in fh:
                m = re.match(r"^([0-9a-fA-F]{32})\s+\*?(.+)$", line.rstrip("\n"))
                if m:
                    exp[os.path.normpath(m.group(2))] = (m.group(1).lower(), None)
    if args.files_tsv:   # tab-separated with columns dest_dir, filename, md5, bytes (the sra-ena-geo-download manifest)
        with open(args.files_tsv, newline="") as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                rel = os.path.normpath(os.path.join(r.get("dest_dir") or "", r["filename"]))
                b = r.get("bytes")
                exp[rel] = ((r.get("md5") or "").lower() or None, int(b) if b and b.isdigit() else None)
    return exp


def cmd_inventory(a):
    root = a.dir
    exp = load_expected(a)
    seen, sums = set(), defaultdict(list)
    for dp, _, fs in os.walk(root):
        for f in sorted(fs):
            p = os.path.join(dp, f)
            rel = os.path.normpath(os.path.relpath(p, root))
            seen.add(rel)
            if os.path.islink(p) and not os.path.exists(p):
                report("ERROR", "broken-symlink", rel); continue
            size = os.path.getsize(p)
            if size == 0:
                report("ERROR", "zero-byte", rel); continue
            if f.endswith(INCOMPLETE):
                report("ERROR", "incomplete-download", rel, "partial-download marker file; the transfer did not finish"); continue
            if os.path.exists(p + ".aria2"):
                report("ERROR", "incomplete-download", rel, "aria2 control file present next to it")
            if f.endswith(".gz"):
                ok, why = gz_ok(p, a.gz_test)
                if not ok:
                    report("ERROR", "gzip-corrupt", rel, why); continue
            if a.md5 or rel in exp:
                digest = md5_file(p); sums[digest].append(rel)
                want = exp.get(rel)
                if want and want[0]:
                    report("OK" if digest == want[0] else "ERROR", "md5", rel, "" if digest == want[0] else f"got {digest}, expected {want[0]}")
                if want and want[1] is not None and want[1] != size:
                    report("ERROR", "size", rel, f"{size} bytes, expected {want[1]}")
    for rel in sorted(set(exp) - seen):
        report("ERROR", "missing-file", rel, "listed in the expectation file but not on disk")
    for d, rels in sums.items():
        if len(rels) > 1 and not a.allow_duplicates:
            report("WARN", "identical-content", ";".join(sorted(rels)), f"md5 {d}")
    if not seen:
        report("ERROR", "empty-directory", root)
    else:
        report("INFO", "inventory", root, f"{len(seen)} files")


# ---------------------------------------------------------------- fastq
FQ_RE = re.compile(r"^(?P<stem>.+?)(?P<sep>[_.])(?P<tag>R?[12]|I[12]|R[123])(?P<tail>(?:_001)?\.f(?:ast)?q(?:\.gz)?)$")


def fastq_pairs(files):
    groups = defaultdict(dict)
    for f in files:
        m = FQ_RE.match(os.path.basename(f))
        if not m:
            continue
        key = (os.path.dirname(f), m.group("stem"), m.group("sep"), m.group("tail"))
        tag = m.group("tag")
        groups[key]["R" + tag[-1] if tag in ("1", "2", "R1", "R2") else tag] = f
    return groups


def fq_scan(path, max_reads):
    n, names, problems = 0, [], []
    with opener(path) as fh:
        while True:
            h = fh.readline()
            if not h:
                break
            s, p, q = fh.readline(), fh.readline(), fh.readline()
            n += 1
            if not q:
                problems.append(f"truncated record {n}"); break
            if not h.startswith("@") or not p.startswith("+"):
                problems.append(f"malformed record {n}"); break
            if len(s.rstrip("\r\n")) != len(q.rstrip("\r\n")):
                problems.append(f"sequence/quality length differ at record {n}"); break
            if max_reads is None or n <= max_reads:
                names.append(re.split(r"[ \t]", h[1:].rstrip("\r\n"))[0].removesuffix("/1").removesuffix("/2"))
            if max_reads is not None and n >= max_reads:
                n = -n  # sentinel: stopped early, count is a lower bound
                break
    return n, names, problems


def cmd_fastq(a):
    files = []
    for dp, _, fs in os.walk(a.dir):
        files += [os.path.join(dp, f) for f in fs if re.search(r"\.f(ast)?q(\.gz)?$", f)]
    if not files:
        report("ERROR", "no-fastq", a.dir); return
    groups = fastq_pairs(files)
    grouped = {f for g in groups.values() for f in g.values()}
    for f in sorted(set(files) - grouped):
        report("INFO", "unrecognised-name", os.path.relpath(f, a.dir), "file name has no _R1/_R2/_1/_2/_I1/_I2 tag; scanned alone")
    scan = {}
    for f in sorted(files):
        try:
            scan[f] = fq_scan(f, a.max_reads)
        except (OSError, EOFError, zlib.error) as e:
            scan[f] = (0, [], [f"unreadable: {e}"])
        n, _, probs = scan[f]
        rel = os.path.relpath(f, a.dir)
        for pr in probs:
            report("ERROR", "fastq-structure", rel, pr)
        if n == 0 and not probs:
            report("ERROR", "fastq-empty", rel)
    for key, g in sorted(groups.items()):
        label = os.path.relpath(os.path.join(key[0], key[1]), a.dir)
        mates = sorted(g)
        if len(mates) == 1 and mates[0] in ("R1", "R2") and not a.single_end:
            report("WARN", "unpaired", label, f"only {mates[0]} found (use --single-end if intended)"); continue
        if "R1" in g and "R2" in g:
            (n1, nm1, _), (n2, nm2, _) = scan[g["R1"]], scan[g["R2"]]
            if (n1 < 0) != (n2 < 0) or (n1 > 0 and n2 > 0 and n1 != n2) or (n1 < 0 and n2 < 0 and n1 != n2):
                report("ERROR", "mate-count", label, f"R1 {abs(n1)} vs R2 {abs(n2)} reads" + (" (lower bounds; scan was capped)" if n1 < 0 else ""))
            else:
                report("OK", "mate-count", label, f"{abs(n1)} reads" + (" (capped)" if n1 < 0 else ""))
            if nm1 != nm2:
                k = next((i for i, (x, y) in enumerate(zip(nm1, nm2)) if x != y), min(len(nm1), len(nm2)))
                report("ERROR", "mate-names", label, f"read names differ first at record {k + 1}")
        others = [m for m in mates if m not in ("R1", "R2")]
        if others and ("R1" in g):
            for m in others:
                if scan[g[m]][0] != scan[g["R1"]][0]:
                    report("ERROR", "index-read-count", label, f"{m} {abs(scan[g[m]][0])} vs R1 {abs(scan[g['R1']][0])}")
    report("INFO", "fastq", a.dir, f"{len(files)} files, {len(groups)} sets")


# ---------------------------------------------------------------- matrix
def find(d, names):
    for n in names:
        p = os.path.join(d, n)
        if os.path.exists(p):
            return p
    return None


def read_table(path, sep):
    with opener(path) as fh:
        return [r for r in csv.reader(fh, delimiter=sep)]


ENS = re.compile(r"^ENS[A-Z]*G\d{6,}(\.\d+)?$")


def cmd_matrix(a):
    d = a.dir
    mtx = find(d, ["matrix.mtx.gz", "matrix.mtx", "count_matrix.mtx.gz", "count_matrix.mtx"])
    if not mtx:
        report("ERROR", "no-matrix", d, "no matrix.mtx(.gz) or count_matrix.mtx(.gz)"); return
    parse = os.path.basename(mtx).startswith("count_matrix")
    genes_p = find(d, ["all_genes.csv.gz", "all_genes.csv"] if parse else ["features.tsv.gz", "genes.tsv.gz", "features.tsv", "genes.tsv"])
    cells_p = find(d, ["cell_metadata.csv.gz", "cell_metadata.csv"] if parse else ["barcodes.tsv.gz", "barcodes.tsv"])
    for p, what in ((genes_p, "gene annotation"), (cells_p, "cell annotation")):
        if not p:
            report("ERROR", "missing-annotation", d, f"{what} file not found"); return
    sep = "," if parse else "\t"
    grows, crows = read_table(genes_p, sep), read_table(cells_p, sep)
    if parse:
        grows, crows = grows[1:], crows[1:]     # these carry a header row
    if not grows or not crows:
        report("ERROR", "empty-annotation", d); return
    gid_col = 0
    if parse:
        hdr = read_table(genes_p, sep)[0]
        gid_col = hdr.index("gene_id") if "gene_id" in hdr else 0
        gname_col = hdr.index("gene_name") if "gene_name" in hdr else gid_col
    else:
        gname_col = 1 if len(grows[0]) > 1 else 0
    gids, gnames = [r[gid_col] for r in grows], [r[gname_col] for r in grows]
    cell_col = 0
    if parse:
        chdr = read_table(cells_p, sep)[0]
        cell_col = chdr.index("bc_wells") if "bc_wells" in chdr else 0
    cells = [r[cell_col] for r in crows]
    report("INFO", "layout", d, f"{'Parse' if parse else '10x'}: {len(gids)} genes, {len(cells)} cells in annotation")
    # header of the mtx
    with opener(mtx) as fh:
        line = fh.readline()
        if not line.startswith("%%MatrixMarket"):
            report("ERROR", "mtx-header", mtx, "missing %%MatrixMarket banner"); return
        field = line.lower().split()[3] if len(line.split()) > 3 else "?"
        while True:
            line = fh.readline()
            if not line.startswith("%"):
                break
        nr, nc, nnz = (int(x) for x in line.split()[:3])
        if (nr, nc) == (len(gids), len(cells)):
            orient = "genes_x_cells"
        elif (nr, nc) == (len(cells), len(gids)):
            orient = "cells_x_genes"
        else:
            report("ERROR", "dimensions", d, f"matrix {nr} x {nc} matches neither {len(gids)} genes x {len(cells)} cells nor the transpose"); return
        if len(gids) == len(cells):
            report("WARN", "orientation-ambiguous", d, "square matrix: orientation cannot be inferred from dimensions")
        expected = "cells_x_genes" if parse else "genes_x_cells"
        report("OK" if orient == expected else "WARN", "orientation", d, f"{orient}" + ("" if orient == expected else f" (usual for {'Parse' if parse else '10x'} is {expected})"))
        gaxis = 1 if orient == "cells_x_genes" else 0
        n_g, n_c = len(gids), len(cells)
        col_sum = [0.0] * n_c; gene_sum = [0.0] * n_g
        bad_int = neg = oor = nan = 0; seen_nnz = 0
        for line in fh:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) < 3:
                report("ERROR", "mtx-entry", mtx, f"malformed entry after {seen_nnz} entries"); return
            i, j, v = int(parts[0]), int(parts[1]), float(parts[2])
            gi, ci = (j, i) if gaxis == 1 else (i, j)
            seen_nnz += 1
            if not (1 <= gi <= n_g and 1 <= ci <= n_c):
                oor += 1; continue
            if v != v:
                nan += 1; continue
            if v < 0:
                neg += 1
            elif v != int(v):
                bad_int += 1
            col_sum[ci - 1] += v; gene_sum[gi - 1] += v
    if seen_nnz != nnz:
        report("ERROR", "nnz", mtx, f"header says {nnz} entries, file has {seen_nnz} (truncated or edited?)")
    else:
        report("OK", "nnz", mtx, f"{nnz} entries")
    for cnt, name, msg in ((oor, "index-range", "entries outside the matrix"), (nan, "nan-values", "NaN entries"), (neg, "negative-values", "negative entries")):
        if cnt:
            report("ERROR", name, mtx, f"{cnt} {msg}")
    if field not in ("integer", "real", "?"):
        report("WARN", "mtx-field", mtx, f"unusual field type '{field}'")
    if bad_int:
        report("ERROR" if a.expect == "counts" else "INFO", "non-integer", mtx, f"{bad_int} non-integer entries: normalised or scaled values, not raw counts")
    elif a.expect == "counts":
        report("OK", "integer-counts", mtx, "all entries are integers")
    empty_c = sum(1 for s in col_sum if s == 0); empty_g = sum(1 for s in gene_sum if s == 0)
    report("WARN" if empty_c / n_c > a.max_empty_frac else "OK", "empty-cells", d, f"{empty_c}/{n_c} cells with zero counts")
    report("INFO", "empty-genes", d, f"{empty_g}/{n_g} genes with zero counts")
    srt = sorted(col_sum)
    report("INFO", "depth", d, f"cell total counts min {srt[0]:.0f}, median {srt[len(srt) // 2]:.0f}, max {srt[-1]:.0f}")
    dup_g, dup_c = len(gids) - len(set(gids)), len(cells) - len(set(cells))
    report("ERROR" if dup_g else "OK", "duplicate-gene-ids", d, f"{dup_g} duplicated" if dup_g else "none")
    report("ERROR" if dup_c else "OK", "duplicate-cell-ids", d, f"{dup_c} duplicated" if dup_c else "none")
    dn = len(gnames) - len(set(gnames))
    if dn:
        report("INFO", "duplicate-gene-names", d, f"{dn} gene names are shared by several ids (collapse by id, not name)")
    ens = sum(1 for g in gids if ENS.match(g))
    if ens:
        ver = sum(1 for g in gids if re.search(r"\.\d+$", g))
        pref = Counter(re.match(r"ENS([A-Z]*)G", g).group(1) for g in gids if ENS.match(g))
        report("INFO", "gene-id-style", d, f"Ensembl ids ({ens}/{len(gids)}); versioned: {ver}; species prefixes: {dict(pref)}")
        if len(pref) > 1:
            report("WARN", "mixed-species-ids", d, "Ensembl ids from more than one species prefix (composite reference?)")
    else:
        report("INFO", "gene-id-style", d, "ids are not Ensembl-style (symbols or custom ids)")
    mt = sum(1 for n in gnames if n.startswith(("MT-", "mt-")))
    report("INFO", "mito-genes", d, f"{mt} genes named MT-/mt-" if mt else "no MT-/mt- gene names (nuclei, other naming, or filtered out?)")
    if not parse:
        bc = [c.split("-")[0] for c in cells]
        lens = Counter(len(b) for b in bc)
        report("INFO", "barcode-length", d, f"{dict(lens)}")


# ---------------------------------------------------------------- sample sheet
def sniff_sep(path):
    with open(path) as fh:
        first = fh.readline()
    return "\t" if first.count("\t") >= first.count(",") and "\t" in first else ","


def cmd_samplesheet(a):
    sep = sniff_sep(a.sheet)
    with open(a.sheet, newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=sep))
    if not rows:
        report("ERROR", "empty-sheet", a.sheet); return
    cols = list(rows[0].keys())
    id_col = a.id_col or cols[0]
    file_cols = a.file_cols.split(",") if a.file_cols else [c for c in cols if re.search(r"fastq|file|path|r1|r2", c, re.I)]
    for c in [id_col] + file_cols:
        if c not in cols:
            report("ERROR", "missing-column", a.sheet, c); return
    ids = [(r[id_col] or "").strip() for r in rows]
    for i, s in enumerate(ids, 2):
        raw = rows[i - 2][id_col] or ""
        if not s:
            report("ERROR", "blank-sample-id", a.sheet, f"line {i}")
        elif raw != s:
            report("WARN", "padded-sample-id", s, f"line {i}: leading/trailing whitespace")
        if re.search(r"\s", s):
            report("WARN", "space-in-sample-id", s, f"line {i}: spaces break many pipelines")
    for s, n in Counter(ids).items():
        if s and n > 1 and not a.allow_repeats:
            report("ERROR", "duplicate-sample-id", s, f"{n} rows (use --allow-repeats for multi-lane sheets)")
    referenced = set()
    for i, r in enumerate(rows, 2):
        for c in file_cols:
            v = (r[c] or "").strip()
            if not v:
                report("ERROR", "blank-file-entry", ids[i - 2], f"line {i}, column {c}"); continue
            p = v if os.path.isabs(v) else os.path.join(a.dir, v)
            referenced.add(os.path.normpath(p))
            if not os.path.exists(p):
                report("ERROR", "missing-file", ids[i - 2], f"{v} (column {c})")
            elif os.path.getsize(p) == 0:
                report("ERROR", "zero-byte", ids[i - 2], v)
    if len(referenced) < sum(1 for r in rows for c in file_cols if (r[c] or "").strip()):
        report("WARN", "file-reused", a.sheet, "the same file is listed for more than one entry")
    if a.dir and os.path.isdir(a.dir) and not a.no_orphans:
        pat = re.compile(a.orphan_pattern)
        for dp, _, fs in os.walk(a.dir):
            for f in fs:
                p = os.path.normpath(os.path.join(dp, f))
                if pat.search(f) and p not in referenced:
                    report("WARN", "orphan-file", os.path.relpath(p, a.dir), "on disk but not in the sample sheet")
    report("INFO", "samplesheet", a.sheet, f"{len(rows)} rows, id column '{id_col}', file columns {file_cols}")


# ---------------------------------------------------------------- design
def cmd_design(a):
    sep = sniff_sep(a.meta)
    with open(a.meta, newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=sep))
    if not rows:
        report("ERROR", "empty-metadata", a.meta); return
    factors = [f for f in a.factors.split(",") if f]
    cols = rows[0].keys()
    for c in factors + ([a.unit] if a.unit else []):
        if c not in cols:
            report("ERROR", "missing-column", a.meta, c); return
    for r in rows:
        for f in factors:
            if (r[f] or "").strip() in ("", "NA", "nan", "NaN"):
                report("WARN", "missing-value", f, f"empty value in column {f}"); break
    unit = a.unit
    groups = defaultdict(set); counts = Counter()
    for r in rows:
        k = tuple(r[f] for f in factors); counts[k] += 1; groups[k].add(r[unit] if unit else None)
    for k, n in sorted(counts.items()):
        lab = " / ".join(f"{f}={v}" for f, v in zip(factors, k))
        reps = len(groups[k]) if unit else n
        what = f"{reps} {unit if unit else 'row'}(s)"
        if reps < a.min_n:
            report("WARN", "replicates", lab, f"{what}; fewer than {a.min_n}: no between-replicate variance can be estimated")
        else:
            report("OK", "replicates", lab, what)
        if unit and n > 3 * max(1, reps) and reps < a.min_n:
            report("WARN", "pseudo-replication", lab, f"{n} rows from {reps} {unit}: rows are not independent replicates")
    for f1 in factors:
        for f2 in factors:
            if f1 >= f2:
                continue
            m12, m21 = defaultdict(set), defaultdict(set)
            for r in rows:
                m12[r[f1]].add(r[f2]); m21[r[f2]].add(r[f1])
            if len(m12) > 1 and len(m21) > 1 and all(len(v) == 1 for v in m12.values()) and all(len(v) == 1 for v in m21.values()):
                report("ERROR", "confounded", f"{f1} x {f2}", "every level of one factor coincides with exactly one level of the other: effects cannot be separated")
            elif len(m12) > 1 and all(len(v) == 1 for v in m12.values()):
                report("WARN", "nested", f"{f1} in {f2}", f"each level of {f1} occurs in only one level of {f2}: {f1} effects are not estimable within {f2}")
            elif len(m21) > 1 and all(len(v) == 1 for v in m21.values()):
                report("WARN", "nested", f"{f2} in {f1}", f"each level of {f2} occurs in only one level of {f1}: {f2} effects are not estimable within {f1}")
    report("INFO", "design", a.meta, f"{len(rows)} rows, {len(counts)} group(s) over {factors}")


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="exit 4 on WARN as well as ERROR")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("inventory"); s.add_argument("dir"); s.add_argument("--gz-test", choices=["full", "head", "none"], default="full", help="gzip integrity: read everything, first MiB, or skip [full]")
    s.add_argument("--md5", action="store_true", help="compute md5 of every file (needed to find duplicates)"); s.add_argument("--md5-list", help="md5sum-format file: hash  relative/path")
    s.add_argument("--files-tsv", help="sra-ena-geo-download manifest (dest_dir, filename, md5, bytes), paths relative to DIR"); s.add_argument("--allow-duplicates", action="store_true")
    s.set_defaults(fn=cmd_inventory)
    s = sub.add_parser("fastq"); s.add_argument("dir"); s.add_argument("--max-reads", type=int, default=None, help="scan at most N reads per file (counts become lower bounds)")
    s.add_argument("--single-end", action="store_true"); s.set_defaults(fn=cmd_fastq)
    s = sub.add_parser("matrix"); s.add_argument("dir"); s.add_argument("--expect", choices=["counts", "any"], default="counts")
    s.add_argument("--max-empty-frac", type=float, default=0.5, help="WARN when more than this fraction of cells has zero counts [0.5]"); s.set_defaults(fn=cmd_matrix)
    s = sub.add_parser("samplesheet"); s.add_argument("sheet"); s.add_argument("--dir", default=".", help="base directory for relative paths [.]"); s.add_argument("--id-col"); s.add_argument("--file-cols", help="comma separated; default: columns named like fastq/file/path/r1/r2")
    s.add_argument("--allow-repeats", action="store_true"); s.add_argument("--no-orphans", action="store_true"); s.add_argument("--orphan-pattern", default=r"\.f(ast)?q(\.gz)?$", help="regex of file names that must appear in the sheet")
    s.set_defaults(fn=cmd_samplesheet)
    s = sub.add_parser("design"); s.add_argument("meta"); s.add_argument("--factors", required=True, help="comma separated column names"); s.add_argument("--unit", help="column naming the biological unit (donor, animal, culture)")
    s.add_argument("--min-n", type=int, default=2); s.set_defaults(fn=cmd_design)
    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except (OSError, ValueError, KeyError) as e:
        print(f"dataset_audit.py: {type(e).__name__}: {e}", file=sys.stderr); return 1
    worst = max((SEV[s] for s in findings), default=0)
    c = Counter(findings)
    print(f"dataset_audit: {c.get('ERROR', 0)} error(s), {c.get('WARN', 0)} warning(s), {c.get('OK', 0)} ok", file=sys.stderr)
    return 4 if worst >= (1 if a.strict else 2) else 0


if __name__ == "__main__":
    sys.exit(main())
