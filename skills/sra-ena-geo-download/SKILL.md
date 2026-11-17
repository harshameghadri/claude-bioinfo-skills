---
name: sra-ena-geo-download
description: Download public sequencing data (SRA/ENA runs, GEO series/samples, supplementary files) with verified integrity. Resolves accessions (SRR/ERR, GSM, SRP, PRJNA) to FASTQ URLs with md5 and byte counts, downloads with aria2c (print, direct or pueue queue), falls back from ENA to NCBI SRA Data Locator 'source' files to SRA Toolkit when ENA has no FASTQ, and verifies size and md5. Use for requests such as download GEO/SRA data, fetch FASTQs for an accession, queue many runs, ENA fastq_ftp is empty, prefetch 404, verify downloads, re-download corrupt files.
---

# Public sequencing data download (ENA, SRA, GEO)

One stdlib-only Python tool, `scripts/sra_dl.py`, drives every step. All stages read and write the same table (`files.tsv`), so a run resolved by ENA, by the SRA Data Locator or from a GEO listing is downloaded and verified the same way.

Requirements: `python3` (>= 3.8) and `aria2c`. Optional: `pueue` (queue runner), SRA Toolkit (`prefetch`, `fasterq-dump`) and `pigz` (toolkit routes only).

Run `python3 scripts/sra_dl.py <command> --help` for the options of each command. Paths below are relative to this skill folder; use absolute paths when the working directory differs.

## Procedure

1. **Resolve accessions to runs** when you start from GEO/BioProject/experiment accessions (skip for SRR/ERR/DRR lists).
   `python3 scripts/sra_dl.py resolve --accessions GSM... SRP... --out manifest.tsv [--dest-template '{SampleName}/{LibraryStrategy}']`
   A GSE (series) is not resolved directly: take its SRP/PRJNA from the GEO series page, or list its GSM accessions. Check the manifest's `library_strategy` and `layout` columns against what the study claims before downloading.
2. **Look up FASTQ URLs in ENA.**
   `python3 scripts/sra_dl.py lookup-ena --manifest manifest.tsv --out-dir fastq` (or `--runs SRR... `).
   Output: `files.tsv` (url, md5, bytes per file) and, if anything could not be resolved, `unresolved.tsv`. **Exit code 3 means some accessions are unresolved. Never ignore it**: silent skipping of runs without an ENA FASTQ is the failure this tool exists to prevent.
3. **Walk the fallback ladder for unresolved runs** (details and symptoms in `references/fallback-ladder.md`):
   - Rung 2, NCBI SRA Data Locator raw files: `python3 scripts/sra_dl.py lookup-sdl --manifest unresolved.tsv --kind source --append --out-dir fastq`
   - Rung 3, SRA Toolkit: `python3 scripts/sra_dl.py jobs --kind prefetch --manifest unresolved.tsv --out-dir fastq --job-dir jobs --runner print`
   - For 10x-style submissions where barcode/UMI reads are stored as technical reads, add `--include-technical` to `jobs`, and prefer `lookup-sdl --kind sra` plus `jobs --kind sra-file` (spot-count check).
4. **GEO supplementary files** (count matrices, peak files, `.tar` archives): `python3 scripts/sra_dl.py geo-suppl --series GSE... --sample GSM... --out-dir geo --append`.
5. **Preview, then download.** `fetch` defaults to `--runner print`, which only prints the aria2c commands.
   `python3 scripts/sra_dl.py fetch --files-tsv files.tsv` (inspect), then either
   `... fetch --runner direct --jobs 3` (run now) or `... fetch --runner pueue --pueue-group sra_dl --gate` (queue; `--gate` makes the first job a canary so a systematic failure does not fan out). Set pueue parallelism outside the tool (`pueue parallel N -g sra_dl`).
   Load: 3 parallel jobs x 16 connections each (48 connections) was stable against ENA; 6 parallel jobs produced "Connection refused". Start there.
   Downloads resume (`-c`), check md5 inside aria2c, and never rename onto an existing file. Files already complete (size equals `bytes`, no `.aria2` sidecar) are skipped.
6. **Verify.** `python3 scripts/sra_dl.py verify --files-tsv files.tsv --report-dir verify`
   Exit 4 means failures; `verify/corrupt_files.txt` and `verify/missing_files.txt` list them. Delete the corrupt files, rerun step 5, verify again. For sources without published md5 (GEO), use `--write-sha256` once after download to freeze checksums next to the files.
7. **Record provenance** in the project: accession list, date, tool command lines, `files.tsv`, `verify_report.tsv`, and any fallback used per run.

## Rules that prevent known failures

- Treat exit code 3 (unresolved) and 4 (verify failed) as stop signs, not warnings.
- A file existing on disk does not mean it is complete: aria2c writes to the final filename from the start and keeps a `.aria2` sidecar until done. The tool checks both.
- When a queue system re-parses commands (pueue does), pass arguments as separate tokens or run a script file. Never wrap a command in `bash -c "<long string>"`. The tool refuses arguments containing whitespace, quotes or shell metacharacters on the pueue runner; use `--runner direct` for such URLs.
- Raw "source" files from the Data Locator can include index reads (I1/I2) and multiple lanes. The tool maps `R1/R2` to `RUN_1/RUN_2.fastq.gz`, index reads to `RUN_I1`, and keeps the original names (noted in `files.tsv`) whenever roles are missing or duplicated. Never rename by sorted order alone.
- `fasterq-dump` without `--include-technical` can drop barcode/UMI reads that 10x-style submissions store as technical reads; confirm read lengths and counts against the study before using the output.
- Keep the downloads read-only afterwards and do not edit `files.tsv` by hand; rerun the lookup instead.
- Large downloads and md5 passes take hours. Say so before starting, run them detached or queued, and report the verify summary when done.

## Outputs

`files.tsv` (schema in `references/formats.md`), `unresolved*.tsv`, downloaded files under `--out-dir`, `verify/verify_report.tsv`, `verify/corrupt_files.txt`, `verify/missing_files.txt`, optional job scripts under `jobs/`.

## Testing and offline use

`bash tests/run.sh` runs 28 offline tests, including a real aria2c download from a local HTTP server with md5 verification, resume, corruption detection, a stubbed pueue runner, and the toolkit job scripts with stub binaries. The live ENA, NCBI and GEO endpoints are not called by the tests; to debug a lookup without the network, save a response as `<ACCESSION>.tsv` (ENA), `.json` (SDL), `.html` (GEO) or `.csv` (runinfo) and pass `--offline-dir`.
