#!/usr/bin/env python3
"""sra_dl.py - resolve, download and verify public sequencing data (ENA, NCBI SRA SDL, GEO).

Pipeline (every stage reads/writes the same files.tsv, so stages are interchangeable):

  resolve     -> manifest.tsv                   GSM/SRP/PRJNA/SRX accession -> run list (NCBI SRA runinfo)
  lookup-ena  -> files.tsv (+ unresolved.tsv)   ENA Portal filereport: FASTQ URLs, md5, bytes
  lookup-sdl  -> files.tsv (+ unresolved)       NCBI SRA Data Locator: 'source' FASTQ or .sra objects
  geo-suppl   -> files.tsv                      GEO series/sample supplementary files
  fetch       files.tsv -> aria2c downloads     runner: print | direct | pueue
  verify      files.tsv -> report               size + md5, lists of corrupt/missing files
  jobs        runs -> per-run job scripts       SRA Toolkit routes (prefetch / .sra file -> FASTQ)

Standard library only (Python >= 3.8). External programs: aria2c (fetch), pueue (runner pueue),
prefetch/fasterq-dump/pigz (jobs only, run by the generated job scripts).

Exit codes: 0 ok | 1 error | 2 usage | 3 some accessions unresolved | 4 verification failures.
Network access can be replaced by recorded responses with --offline-dir DIR
(files named <ACCESSION>.tsv for ENA, .json for SDL, .html for GEO, .csv for runinfo).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

EXIT_OK, EXIT_ERR, EXIT_USAGE, EXIT_UNRESOLVED, EXIT_VERIFY = 0, 1, 2, 3, 4
FILES_COLS = ["run", "dest_dir", "filename", "url", "md5", "bytes", "source", "note"]
UNRES_COLS = ["accession", "dest", "reason"]
ENA_URL = "https://www.ebi.ac.uk/ena/portal/api/filereport"
SDL_URL = "https://trace.ncbi.nlm.nih.gov/Traces/sdl/2/retrieve"
RUNINFO_URL = "https://trace.ncbi.nlm.nih.gov/Traces/sra-db-be/runinfo"
GEO_BASE = "https://ftp.ncbi.nlm.nih.gov/geo"
ACC_RE = re.compile(r"^[A-Za-z]{2,5}[0-9]+$")
UNSAFE_FOR_PUEUE = re.compile(r"[\s'\"\\$`;&|<>()]")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


class UsageError(Exception):
    pass


# --------------------------------------------------------------------------- generic helpers
def retry_sleep() -> float:
    return float(os.environ.get("SRA_DL_RETRY_SLEEP", "5"))


def http_get(url: str, tries: int = 4, timeout: int = 60) -> str:
    last: Exception | None = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sra-ena-geo-download/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 404):
                raise
            last = e
        except Exception as e:  # transient network error
            last = e
        if i < tries - 1:
            time.sleep(retry_sleep() * (i + 1))
    assert last is not None
    raise last


def fetch_text(kind: str, acc: str, url: str, offline_dir: str | None) -> str:
    """Return the response body for acc, from recorded fixtures (offline) or the network."""
    if offline_dir:
        ext = {"ena": "tsv", "sdl": "json", "geo": "html", "runinfo": "csv"}[kind]
        p = Path(offline_dir) / f"{acc}.{ext}"
        if not p.is_file():
            raise FileNotFoundError(f"offline fixture missing: {p}")
        return p.read_text(encoding="utf-8")
    return http_get(url)


def check_acc(acc: str) -> str:
    if not ACC_RE.match(acc):
        raise UsageError(f"not an accession: {acc!r} (expected letters then digits, e.g. SRR123456)")
    return acc


def safe_rel(path: str) -> str:
    p = Path(path)
    if p.is_absolute() or ".." in p.parts:
        raise UsageError(f"destination must be a relative path without '..': {path!r}")
    return path


def read_runs(args) -> list[tuple[str, str]]:
    """(accession, dest_subdir) from --runs and/or --manifest. Manifest: TSV with header; columns
    'run' (aliases srr, accession) and optional 'dest' (relative sub-directory)."""
    out: list[tuple[str, str]] = []
    for a in args.runs or []:
        out.append((check_acc(a), "."))
    if args.manifest:
        with open(args.manifest, newline="", encoding="utf-8") as fh:
            rd = csv.DictReader((ln for ln in fh if ln.strip() and not ln.startswith("#")), delimiter="\t")
            cols = {c.lower(): c for c in (rd.fieldnames or [])}
            key = next((cols[k] for k in ("run", "srr", "accession") if k in cols), None)
            if key is None:
                raise UsageError(f"{args.manifest}: need a header with a 'run' (or 'srr'/'accession') column")
            dcol = cols.get("dest")
            for row in rd:
                acc = (row.get(key) or "").strip()
                if acc:
                    out.append((check_acc(acc), safe_rel((row.get(dcol) or ".").strip() or ".") if dcol else "."))
    if not out:
        raise UsageError("no accessions given (use --runs and/or --manifest)")
    seen, uniq = set(), []
    for a, d in out:
        if (a, d) not in seen:
            seen.add((a, d))
            uniq.append((a, d))
    return uniq


def write_tsv(path: str, cols: list[str], rows: list[dict], append: bool = False) -> None:
    exists = append and Path(path).is_file() and Path(path).stat().st_size > 0
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a" if append else "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        if not exists:
            w.writerow(cols)
        for r in rows:
            w.writerow([str(r.get(c, "")).replace("\t", " ").replace("\n", " ") for c in cols])


def read_tsv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def load_files(path: str) -> list[dict]:
    rows = read_tsv(path)
    for need in ("dest_dir", "filename", "url"):
        if rows and need not in rows[0]:
            raise UsageError(f"{path}: missing column {need!r}")
    return rows


def md5_of(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def sha256_of(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def finish_lookup(args, rows, unresolved) -> int:
    write_tsv(args.files_tsv, FILES_COLS, rows, append=args.append)
    if unresolved:
        write_tsv(args.unresolved_tsv, UNRES_COLS, unresolved)
        log(f"{len(unresolved)} accession(s) unresolved -> {args.unresolved_tsv}")
        for u in unresolved:
            log(f"  {u['accession']}\t{u['reason']}")
    elif Path(args.unresolved_tsv).exists():
        Path(args.unresolved_tsv).unlink()
    log(f"{len(rows)} file row(s) -> {args.files_tsv}")
    return EXIT_UNRESOLVED if unresolved else EXIT_OK


# --------------------------------------------------------------------------- resolve (accession -> runs)
def safe_part(x: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", x).strip("._") or "NA"


def cmd_resolve(args) -> int:
    import io
    out_rows, unresolved = [], []
    for i, acc in enumerate(args.accessions):
        check_acc(acc)
        try:
            text = fetch_text("runinfo", acc, f"{RUNINFO_URL}?acc={acc}", args.offline_dir)
            recs = list(csv.DictReader(io.StringIO(text)))
            if not recs or "Run" not in recs[0]:
                raise ValueError("no runs returned (or unexpected response)")
        except Exception as e:
            unresolved.append({"accession": acc, "dest": ".", "reason": f"lookup_failed: {e}"})
            continue
        for r in recs:
            dest = safe_rel("/".join(safe_part(r.get(k, "")) for k in re.findall(r"\{(\w+)\}", args.dest_template))) if args.dest_template else "."
            out_rows.append({"run": r["Run"], "dest": dest, "sample": r.get("SampleName", ""), "library_strategy": r.get("LibraryStrategy", ""),
                             "layout": r.get("LibraryLayout", ""), "spots": r.get("spots", ""), "avg_len": r.get("avgLength", ""),
                             "experiment": r.get("Experiment", ""), "bioproject": r.get("BioProject", ""), "query": acc})
        if not args.offline_dir and i < len(args.accessions) - 1:
            time.sleep(args.sleep)  # be polite to NCBI (original runs used 1 s)
    cols = ["run", "dest", "sample", "library_strategy", "layout", "spots", "avg_len", "experiment", "bioproject", "query"]
    write_tsv(args.out, cols, out_rows)
    log(f"{len(out_rows)} run(s) -> {args.out}")
    if unresolved:
        write_tsv(args.unresolved_tsv, UNRES_COLS, unresolved)
        for u in unresolved:
            log(f"  unresolved {u['accession']}\t{u['reason']}")
    return EXIT_UNRESOLVED if unresolved else EXIT_OK


# --------------------------------------------------------------------------- lookup-ena
def parse_ena(text: str) -> list[dict]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    hdr = lines[0].split("\t")
    if "run_accession" not in hdr or "fastq_ftp" not in hdr:
        raise ValueError("unexpected ENA response (no run_accession/fastq_ftp header)")
    return [dict(zip(hdr, ln.split("\t"))) for ln in lines[1:]]


def cmd_lookup_ena(args) -> int:
    rows, unresolved = [], []
    for acc, dest in read_runs(args):
        url = f"{ENA_URL}?accession={acc}&result=read_run&fields=run_accession,fastq_ftp,fastq_md5,fastq_bytes&format=tsv"
        try:
            recs = parse_ena(fetch_text("ena", acc, url, args.offline_dir))
        except Exception as e:
            unresolved.append({"accession": acc, "dest": dest, "reason": f"lookup_failed: {e}"})
            continue
        if not recs:
            unresolved.append({"accession": acc, "dest": dest, "reason": "not_in_ena"})
            continue
        for rec in recs:
            run = rec.get("run_accession", acc)
            ftps = [u for u in rec.get("fastq_ftp", "").split(";") if u]
            if not ftps:
                unresolved.append({"accession": run, "dest": dest, "reason": "empty_fastq_ftp (not mirrored by ENA; use lookup-sdl or jobs)"})
                continue
            md5s = rec.get("fastq_md5", "").split(";") if rec.get("fastq_md5") else []
            byts = rec.get("fastq_bytes", "").split(";") if rec.get("fastq_bytes") else []
            note = ""
            if len(md5s) != len(ftps):
                md5s, note = [""] * len(ftps), "md5_unavailable"
            if len(byts) != len(ftps):
                byts = [""] * len(ftps)
                note = (note + ";bytes_unavailable").strip(";")
            for u, m, b in zip(ftps, md5s, byts):
                full = u if "://" in u else f"{args.scheme}://{u}"
                rows.append({"run": run, "dest_dir": str(Path(args.out_dir) / dest), "filename": os.path.basename(u),
                             "url": full, "md5": m, "bytes": b, "source": "ena", "note": note})
    return finish_lookup(args, rows, unresolved)


# --------------------------------------------------------------------------- lookup-sdl
MATE_RE = re.compile(r"(?<![A-Za-z0-9])([RI])([12])(?=[._-]|$)")
FASTQ_RE = re.compile(r"\.(fastq|fq)(\.gz)?$", re.I)


def mate_names(run: str, names: list[str]) -> tuple[dict[str, str], str]:
    """Map original SDL file names to standard names. R1/R2 -> RUN_1/RUN_2 fastq.gz, I1/I2 -> RUN_I1/RUN_I2.
    Keep original names (and say so) when roles are missing, duplicated (multi-lane) or not FASTQ."""
    if not all(FASTQ_RE.search(n) for n in names):
        return {n: n for n in names}, "kept_original_names:not_all_fastq"
    roles = {}
    for n in names:
        m = MATE_RE.search(n)
        if not m:
            return {x: x for x in names}, "kept_original_names:mate_not_detected"
        roles[n] = m.group(1) + m.group(2)
    if len(set(roles.values())) != len(names):
        return {x: x for x in names}, "kept_original_names:duplicate_roles(multi-lane?)"
    out = {n: (f"{run}_{r[1]}.fastq.gz" if r[0] == "R" else f"{run}_{r}.fastq.gz") for n, r in roles.items()}
    return out, ""


def cmd_lookup_sdl(args) -> int:
    rows, unresolved = [], []
    for acc, dest in read_runs(args):
        url = f"{SDL_URL}?acc={acc}"
        try:
            data = json.loads(fetch_text("sdl", acc, url, args.offline_dir))
        except Exception as e:
            unresolved.append({"accession": acc, "dest": dest, "reason": f"lookup_failed: {e}"})
            continue
        files = [f for r in data.get("result", []) for f in r.get("files", []) if f.get("type") == args.kind]
        files = [f for f in files if f.get("locations")]
        if not files:
            unresolved.append({"accession": acc, "dest": dest, "reason": f"no '{args.kind}' object with a download location in SDL"})
            continue
        ddir = str(Path(args.out_dir) / dest)
        if args.kind == "sra":
            names, note = {files[0]["name"]: f"{acc}.sra"}, ""
            files = files[:1]
        else:
            names, note = mate_names(acc, [f["name"] for f in files])
        for f in sorted(files, key=lambda x: names[x["name"]]):
            rows.append({"run": acc, "dest_dir": ddir, "filename": names[f["name"]], "url": f["locations"][0]["link"],
                         "md5": f.get("md5", ""), "bytes": f.get("size", ""), "source": f"sdl-{args.kind}", "note": note})
        if note:
            log(f"  [{acc}] {note}")
    return finish_lookup(args, rows, unresolved)


# --------------------------------------------------------------------------- geo-suppl
def geo_dir_url(kind: str, acc: str) -> str:
    stub = acc[:-3] + "nnn"
    return f"{GEO_BASE}/{'series' if kind == 'series' else 'samples'}/{stub}/{acc}/suppl/"


def cmd_geo_suppl(args) -> int:
    rows, unresolved = [], []
    targets = [("series", check_acc(a)) for a in args.series or []] + [("sample", check_acc(a)) for a in args.sample or []]
    if not targets:
        raise UsageError("give --series GSE... and/or --sample GSM...")
    for kind, acc in targets:
        url = geo_dir_url(kind, acc)
        try:
            html = fetch_text("geo", acc, url, args.offline_dir)
        except Exception as e:
            unresolved.append({"accession": acc, "dest": ".", "reason": f"lookup_failed: {e}"})
            continue
        names = [m.group(1) for m in re.finditer(r'<a href="([^"?/:]+)">', html)]  # relative file links only
        if not names:
            unresolved.append({"accession": acc, "dest": ".", "reason": "no supplementary files listed"})
            continue
        for n in names:
            rows.append({"run": acc, "dest_dir": str(Path(args.out_dir) / acc), "filename": n, "url": url + n,
                         "md5": "", "bytes": "", "source": "geo", "note": "no_md5_published;use verify --write-sha256"})
    return finish_lookup(args, rows, unresolved)


# --------------------------------------------------------------------------- fetch
def aria_cmd(row: dict, a) -> list[str]:
    cmd = [a.aria2c, "-c", "-x", str(a.connections), "-s", str(a.split), "--retry-wait=10", "--max-tries=10",
           "--file-allocation=none", "--auto-file-renaming=false", f"--dir={row['dest_dir']}", f"--out={row['filename']}"]
    if row.get("md5"):
        cmd.append(f"--checksum=md5={row['md5']}")
    cmd.append(row["url"])
    return cmd


def already_complete(row: dict) -> bool:
    p = Path(row["dest_dir"]) / row["filename"]
    if not p.is_file() or Path(str(p) + ".aria2").exists():  # .aria2 sidecar = download still in flight
        return False
    return bool(row.get("bytes")) and p.stat().st_size == int(row["bytes"])


def queue_commands(cmds: list[list[str]], labels: list[str], a) -> int:
    """Run or queue argv lists. Returns number of failures (direct runner) or 0."""
    if a.runner == "print":
        for c in cmds:
            print(" ".join(shlex.quote(x) for x in c))
        return 0
    if a.runner == "pueue":
        for c in cmds:
            bad = [x for x in c if UNSAFE_FOR_PUEUE.search(x)]
            if bad:
                raise UsageError(f"argument not safe to pass through pueue (whitespace/quote/shell characters): {bad[0]!r}; "
                                 "use --runner direct or fix the path")
        subprocess.run(["pueue", "group", "add", a.pueue_group], stderr=subprocess.DEVNULL, check=False)
        gate = None
        for c, lab in zip(cmds, labels):
            add = ["pueue", "add", "-g", a.pueue_group, "-l", lab]
            if a.gate and gate is None:
                add.append("-p")
            elif a.gate:
                add += ["--after", gate]
            r = subprocess.run(add + ["--"] + c, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"pueue add failed for {lab}: {r.stderr.strip()}")
            if a.gate and gate is None:
                gate = r.stdout.strip().split()[-1]
                log(f"gate job id {gate}: remaining jobs start only if it succeeds")
        log(f"queued {len(cmds)} job(s) in pueue group '{a.pueue_group}'. Set parallelism outside this tool: "
            f"pueue parallel N -g {a.pueue_group}; retry failures: pueue restart --failed-in-group {a.pueue_group}")
        return 0
    failed = 0
    with cf.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        futs = {ex.submit(subprocess.run, c): lab for c, lab in zip(cmds, labels)}
        for f in cf.as_completed(futs):
            rc = f.result().returncode
            if rc != 0:
                failed += 1
                log(f"FAILED ({rc}): {futs[f]}")
    return failed


def cmd_fetch(args) -> int:
    if args.runner != "print" and not shutil.which(args.aria2c):
        raise UsageError(f"{args.aria2c} not found on PATH (install aria2) or use --runner print")
    rows = load_files(args.files_tsv)
    todo, skipped = [], 0
    for r in rows:
        if already_complete(r):
            skipped += 1
            continue
        todo.append(r)
    if args.runner != "print":
        for r in todo:
            Path(r["dest_dir"]).mkdir(parents=True, exist_ok=True)
    failed = queue_commands([aria_cmd(r, args) for r in todo], [f"dl_{r['run']}_{r['filename']}" for r in todo], args)
    log(f"files: {len(rows)}  to download: {len(todo)}  already complete: {skipped}  failed: {failed}")
    return EXIT_ERR if failed else EXIT_OK


# --------------------------------------------------------------------------- verify
def check_one(row: dict, use_md5: bool) -> dict:
    p = Path(row["dest_dir"]) / row["filename"]
    res = {"run": row.get("run", ""), "path": str(p), "status": "ok", "detail": ""}
    if not p.is_file():
        res["status"] = "missing"
    elif Path(str(p) + ".aria2").exists():
        res["status"] = "incomplete"
        res["detail"] = ".aria2 sidecar present"
    elif row.get("bytes") and p.stat().st_size != int(row["bytes"]):
        res["status"], res["detail"] = "size_mismatch", f"{p.stat().st_size} != {row['bytes']}"
    elif not row.get("md5"):
        res["status"], res["detail"] = ("no_md5_size_ok" if row.get("bytes") else "no_md5_no_size"), ""
    elif use_md5:
        got = md5_of(p)
        if got != row["md5"]:
            res["status"], res["detail"] = "md5_mismatch", f"{got} != {row['md5']}"
    else:
        res["detail"] = "md5 skipped"
    return res


def cmd_verify(args) -> int:
    rows = load_files(args.files_tsv)
    with cf.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        results = list(ex.map(lambda r: check_one(r, not args.no_md5), rows))
    rd = Path(args.report_dir)
    rd.mkdir(parents=True, exist_ok=True)
    write_tsv(str(rd / "verify_report.tsv"), ["run", "path", "status", "detail"], results)
    bad_status = {"size_mismatch", "md5_mismatch", "incomplete"}
    (rd / "corrupt_files.txt").write_text("".join(r["path"] + "\n" for r in results if r["status"] in bad_status))
    (rd / "missing_files.txt").write_text("".join(r["path"] + "\n" for r in results if r["status"] == "missing"))
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    log("verify: " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if args.write_sha256:
        by_dir: dict[str, list[str]] = {}
        for r in results:
            if r["status"] not in ("missing", "incomplete"):
                by_dir.setdefault(str(Path(r["path"]).parent), []).append(r["path"])
        for d, paths in by_dir.items():
            with open(Path(d) / "SHA256SUMS", "w") as fh:
                for p in sorted(paths):
                    fh.write(f"{sha256_of(Path(p))}  {os.path.basename(p)}\n")
    bad = sum(v for k, v in counts.items() if k in bad_status | {"missing"})
    return EXIT_VERIFY if bad else EXIT_OK


# --------------------------------------------------------------------------- jobs (SRA Toolkit routes)
TOOLKIT_JOB = """#!/usr/bin/env bash
# {run}: prefetch -> fasterq-dump -> pigz -> remove cache. Generated by sra_dl.py jobs --kind prefetch.
set -euo pipefail
RUN={run}
OUT={out}
CACHE={cache}/$RUN
SRA_BIN={sra_bin}
mkdir -p "$CACHE/tmp" "$OUT"
"$SRA_BIN/prefetch" "$RUN" --output-directory "$CACHE"
"$SRA_BIN/fasterq-dump" "$CACHE/$RUN" --split-files {tech} --threads {threads} --temp "$CACHE/tmp" --outdir "$OUT"
shopt -s nullglob
fq=("$OUT/${{RUN}}"*.fastq)
(( ${{#fq[@]}} > 0 )) || {{ echo "no FASTQ produced for $RUN" >&2; exit 1; }}
{pigz} -f "${{fq[@]}}"
rm -rf "$CACHE"
echo "done $RUN"
"""

SRAFILE_JOB = """#!/usr/bin/env bash
# {run}: local .sra -> fasterq-dump -> spot check -> pigz -> sha256 manifest. Generated by sra_dl.py jobs --kind sra-file.
set -euo pipefail
RUN={run}
SRA={sra}
OUT={out}
EXPECT_SPOTS={spots}
W="$OUT/.work_$RUN"
mkdir -p "$W/tmp" "$OUT"
{fqd} "$SRA" --split-files {tech} --threads {threads} --temp "$W/tmp" --outdir "$W" 2>&1 | tee "$W/fasterq.log"
if [[ -n "$EXPECT_SPOTS" ]]; then
  got=$(grep -i 'spots read' "$W/fasterq.log" | tr -dc 0-9)
  [[ "$got" == "$EXPECT_SPOTS" ]] || {{ echo "spot mismatch for $RUN: got '$got' expected '$EXPECT_SPOTS'" >&2; exit 1; }}
else
  echo "WARNING: no expected spot count given; spot check skipped" >&2
fi
shopt -s nullglob
fq=("$W/${{RUN}}"*.fastq)
(( ${{#fq[@]}} > 0 )) || {{ echo "no FASTQ produced for $RUN" >&2; exit 1; }}
printf 'file\\tsha256\\n' > "$W/manifest.tsv"
for f in "${{fq[@]}}"; do
  {pigz} -f "$f"
  mv "$f.gz" "$OUT/"
  printf '%s\\t%s\\n' "$(basename "$f").gz" "$({sha})" >> "$W/manifest.tsv"
done
mv "$W/manifest.tsv" "$OUT/$RUN.download_manifest.tsv"
rm -rf "$W"
echo "done $RUN"
"""


def sha_expr() -> str:
    if shutil.which("sha256sum"):
        return 'sha256sum "$OUT/$(basename "$f").gz" | cut -d" " -f1'
    return 'shasum -a 256 "$OUT/$(basename "$f").gz" | cut -d" " -f1'


def cmd_jobs(args) -> int:
    runs = read_runs(args)
    job_dir = Path(args.job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    spots = {}
    if args.manifest:  # optional 'spots' column for the spot-count check
        for r in read_tsv(args.manifest):
            k = next((r[c] for c in ("run", "srr", "accession") if c in r), "")
            if r.get("spots"):
                spots[k] = r["spots"]
    scripts, labels = [], []
    tech = "--include-technical" if args.include_technical else ""
    for acc, dest in runs:
        out = Path(args.out_dir) / dest
        if args.kind == "prefetch":
            body = TOOLKIT_JOB.format(run=acc, out=shlex.quote(str(out)), cache=shlex.quote(args.cache_root),
                                      sra_bin=shlex.quote(args.sra_bin), tech=tech, threads=args.threads, pigz=args.pigz)
        else:
            sra = Path(args.sra_dir) / f"{acc}.sra" if args.sra_dir else out / f"{acc}.sra"
            body = SRAFILE_JOB.format(run=acc, sra=shlex.quote(str(sra)), out=shlex.quote(str(out)), spots=shlex.quote(spots.get(acc, "")),
                                      fqd=shlex.quote(os.path.join(args.sra_bin, "fasterq-dump")) if args.sra_bin else "fasterq-dump",
                                      tech=tech, threads=args.threads, pigz=args.pigz, sha=sha_expr())
        p = job_dir / f"{acc}.sh"
        p.write_text(body)
        p.chmod(0o755)
        chk = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True)
        if chk.returncode != 0:
            raise RuntimeError(f"generated job script has a syntax error: {p}: {chk.stderr}")
        scripts.append(p)
        labels.append(f"job_{acc}")
    log(f"wrote {len(scripts)} job script(s) to {job_dir}")
    cmds = [["bash", str(p.resolve())] for p in scripts]
    failed = queue_commands(cmds, labels, args)
    return EXIT_ERR if failed else EXIT_OK


# --------------------------------------------------------------------------- CLI
def add_common_lookup(p, kind_default_unres: str):
    p.add_argument("--runs", nargs="*", help="accessions (SRR/ERR/DRR, or a project/study accession for lookup-ena)")
    p.add_argument("--manifest", help="TSV with header; column 'run' (or srr/accession) and optional relative 'dest'")
    p.add_argument("--out-dir", default="fastq", help="root download directory (default: fastq)")
    p.add_argument("--files-tsv", default="files.tsv")
    p.add_argument("--unresolved-tsv", default=kind_default_unres)
    p.add_argument("--append", action="store_true", help="append to files.tsv instead of overwriting")
    p.add_argument("--offline-dir", help="use recorded responses (<ACC>.tsv|.json|.html) instead of the network")


def add_runner(p):
    p.add_argument("--runner", choices=["print", "direct", "pueue"], default="print",
                   help="print = show commands only (default); direct = run now; pueue = queue in pueue")
    p.add_argument("--jobs", type=int, default=3, help="parallel jobs for --runner direct (default 3)")
    p.add_argument("--pueue-group", default="sra_dl")
    p.add_argument("--gate", action="store_true", help="pueue: first job gates the rest (they start only if it succeeds)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="sra_dl.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("resolve", help="GSM/SRP/PRJNA/SRX accession -> run manifest (NCBI SRA runinfo)")
    p.add_argument("--accessions", nargs="+", required=True)
    p.add_argument("--out", default="manifest.tsv")
    p.add_argument("--unresolved-tsv", default="unresolved_resolve.tsv")
    p.add_argument("--dest-template", default="", help="relative sub-directory per run built from runinfo columns, e.g. '{SampleName}/{LibraryStrategy}'")
    p.add_argument("--sleep", type=float, default=1.0, help="seconds between NCBI queries (default 1)")
    p.add_argument("--offline-dir")
    p.set_defaults(fn=cmd_resolve)

    p = sub.add_parser("lookup-ena", help="ENA filereport -> files.tsv")
    add_common_lookup(p, "unresolved.tsv")
    p.add_argument("--scheme", choices=["http", "https"], default="http", help="scheme for scheme-less ENA URLs (default http)")
    p.set_defaults(fn=cmd_lookup_ena)

    p = sub.add_parser("lookup-sdl", help="NCBI SRA Data Locator -> files.tsv ('source' FASTQ or .sra)")
    add_common_lookup(p, "unresolved_sdl.tsv")
    p.add_argument("--kind", choices=["source", "sra"], default="source")
    p.set_defaults(fn=cmd_lookup_sdl)

    p = sub.add_parser("geo-suppl", help="GEO supplementary file listing -> files.tsv")
    p.add_argument("--series", nargs="*", help="GSE accessions")
    p.add_argument("--sample", nargs="*", help="GSM accessions")
    p.add_argument("--out-dir", default="geo")
    p.add_argument("--files-tsv", default="files.tsv")
    p.add_argument("--unresolved-tsv", default="unresolved_geo.tsv")
    p.add_argument("--append", action="store_true")
    p.add_argument("--offline-dir")
    p.set_defaults(fn=cmd_geo_suppl)

    p = sub.add_parser("fetch", help="download everything in files.tsv with aria2c")
    p.add_argument("--files-tsv", default="files.tsv")
    p.add_argument("--aria2c", default="aria2c")
    p.add_argument("--connections", type=int, default=16, help="aria2c -x (default 16)")
    p.add_argument("--split", type=int, default=16, help="aria2c -s (default 16)")
    add_runner(p)
    p.set_defaults(fn=cmd_fetch)

    p = sub.add_parser("verify", help="check size and md5 of downloaded files")
    p.add_argument("--files-tsv", default="files.tsv")
    p.add_argument("--report-dir", default="verify")
    p.add_argument("--no-md5", action="store_true", help="size check only (fast)")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--write-sha256", action="store_true", help="write SHA256SUMS next to the files (for sources without md5, e.g. GEO)")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("jobs", help="write per-run SRA Toolkit job scripts (prefetch, or local .sra -> FASTQ)")
    p.add_argument("--kind", choices=["prefetch", "sra-file"], required=True)
    p.add_argument("--runs", nargs="*")
    p.add_argument("--manifest", help="TSV with 'run' and optional 'dest' and 'spots' columns")
    p.add_argument("--out-dir", default="fastq")
    p.add_argument("--job-dir", default="jobs")
    p.add_argument("--sra-dir", help="sra-file: directory holding RUN.sra (default: the run's out dir)")
    p.add_argument("--sra-bin", default="", help="directory with prefetch/fasterq-dump (default: use PATH)")
    p.add_argument("--cache-root", default="sra_cache")
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--pigz", default="pigz")
    p.add_argument("--include-technical", action="store_true", help="fasterq-dump --include-technical: keeps barcode/UMI reads of 10x-style submissions")
    add_runner(p)
    p.set_defaults(fn=cmd_jobs)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except UsageError as e:
        log(f"error: {e}")
        return EXIT_USAGE
    except Exception as e:
        log(f"error: {type(e).__name__}: {e}")
        return EXIT_ERR


if __name__ == "__main__":
    sys.exit(main())
