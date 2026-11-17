---
name: dataset-audit
description: Audit a sequencing dataset before analysis, whether downloaded or received. Checks file completeness and checksums, gzip and FASTQ integrity and mate pairing, 10x and Parse count-matrix dimensions, orientation, integer counts and duplicate ids, sample sheets against files on disk, and experimental design (replicates per group, confounded or nested factors, pseudo-replication). Also gives a checklist for auditing a public GEO/SRA dataset against its paper. Use for dataset QC, 'is this data usable', pre-analysis checks, replicate counts, batch confounding.
---

# Dataset audit (before any analysis)

Most expensive mistakes are visible in the files and the design table before any model is fitted: a truncated download, mates with different read counts, a matrix read the wrong way round, normalised values mistaken for counts, a treatment fully confounded with a batch, one replicate per group. This skill runs those checks with one standard-library script and gives a checklist for the part no script can do (reading the paper and the repository metadata).

Requirements: `python3` (>= 3.8, standard library only). Run `python3 scripts/dataset_audit.py --help` and `<subcommand> --help`. Paths are relative to this skill folder.

## Output convention

Each finding is one tab-separated line: `SEVERITY  check  subject  detail` (ERROR, WARN, INFO, OK) on stdout; a count summary goes to stderr. Exit codes: 0 no ERROR, 4 at least one ERROR (put `--strict` before the subcommand to fail on WARN too), 1 internal error, 2 usage. Save the output to a file and keep it with the project: it is the audit record.

## Procedure

1. **Inventory the files** (after download or transfer):
   `python3 scripts/dataset_audit.py inventory DIR [--md5-list sums.md5 | --files-tsv files.tsv] [--gz-test full|head|none]`
   Finds zero-byte files, partial-download markers (`.aria2`, `.part`, `.tmp`), truncated gzip files, files missing against an expectation list and md5/size mismatches. `--files-tsv` accepts the manifest written by the `sra-ena-geo-download` skill. `--md5` also reports identical files stored under different names. For multi-terabyte data use `--gz-test head` first.
2. **FASTQ.** `python3 scripts/dataset_audit.py fastq DIR [--max-reads N] [--single-end]`
   Checks record structure, sequence/quality length, equal read counts between R1 and R2 (and index reads), identical read names between mates. `--max-reads` caps the scan (counts are then lower bounds and say so).
3. **Count matrices.** `python3 scripts/dataset_audit.py matrix DIR [--expect counts|any]`
   Works on a 10x folder (`matrix.mtx`, `features.tsv`, `barcodes.tsv`) or a Parse folder (`count_matrix.mtx`, `all_genes.csv`, `cell_metadata.csv`). Reports dimensions against the annotation, orientation (and whether it is the usual one for that platform), non-integer or negative values, out-of-range indices, entry count against the header, duplicate ids, empty cells, Ensembl id style and species prefixes, mitochondrial gene naming, depth summary.
4. **Sample sheet.** `python3 scripts/dataset_audit.py samplesheet sheet.csv --dir DATA_DIR [--id-col sample] [--file-cols fastq_1,fastq_2] [--allow-repeats]`
   Missing or zero-byte files, blank entries, duplicated or space-containing sample ids, files listed twice, and FASTQ files on disk that no row refers to.
5. **Design.** `python3 scripts/dataset_audit.py design metadata.tsv --factors condition,batch [--unit donor] [--min-n 2]`
   Replicates per group (counted as distinct `--unit` values when given), pseudo-replication (many rows from one unit), perfectly confounded factor pairs (ERROR), nested factors (WARN), missing values.
6. **Public dataset? Do the paper-side audit** (no script can do this; write the answers into the audit record):
   - Accession, repository release date and the paper's data-availability statement agree; list every sample accession with its condition, replicate and batch.
   - Replicate counts: compare the repository metadata, the paper's methods and the figure legends. Discrepancies are common; resolve them or state which source you trust and why.
   - What a "replicate" is: biological unit (animal, donor, culture) versus technical (well, lane, section, cell). Cells and spots are not replicates.
   - Chemistry/platform, reference genome and annotation release, processed versus raw files provided, and whether the processed matrix is filtered or normalised.
   - Confounds visible in the metadata: batch, sex, age, sequencing run, processing date versus condition.
   - What question the data can and cannot answer, and the smallest unit at which any claim can be tested.
7. **Decide and record.** State go / go-with-caveats / stop, list every ERROR and WARN with the action taken, and keep the audit output next to the data.

## Rules that prevent known failures

- A SKIP or a capped scan is not a pass; say what was not checked.
- Never fix a finding by editing the raw files in place. Re-download or request the data again, or work on a corrected copy and log the change.
- An md5 can only be compared with the value the data provider published; an md5 computed after a damaged transfer proves nothing.
- A matrix that reads without error can still be transposed or normalised. Dimensions against the annotation tables decide orientation; a square matrix is ambiguous and is reported as such.
- Counts per group are counted in biological units. If the design table lacks a unit column, add one before trusting any replicate count.

## Outputs

The tab-separated findings per run (save them), nothing is written to the data directories.

## Testing

`bash tests/run.sh` (39 tests, synthetic files generated on the fly, no network): truncated and corrupt gzip, partial-download markers, md5 and manifest mismatches, mate count and name mismatches, malformed FASTQ, 10x and Parse layouts in both orientations, non-integer, negative, out-of-range and truncated matrices, duplicate ids, sample-sheet defects, confounded, nested and unreplicated designs, and exit codes. Details: `references/checks.md`.
