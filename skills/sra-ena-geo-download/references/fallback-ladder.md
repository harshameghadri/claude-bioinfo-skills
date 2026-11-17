# Fallback ladder: where FASTQ files come from

Try the rungs in order. Each rung exists because the one above it was observed to fail for real runs.

| Rung | Command | Works when | Typical symptom that sends you to the next rung |
|---|---|---|---|
| 1. ENA mirror | `lookup-ena` | ENA has processed FASTQ for the run (most runs) | `empty_fastq_ftp` in `unresolved.tsv`: the run is new, or ENA never mirrored it |
| 2. SRA Data Locator "source" files | `lookup-sdl --kind source` | the submitter's original FASTQ files are stored as raw objects | `no 'source' object` in `unresolved_sdl.tsv` |
| 3. SRA Toolkit | `jobs --kind prefetch` (or `lookup-sdl --kind sra` + `fetch` + `jobs --kind sra-file`) | the run exists as a normalised `.sra` object | `prefetch` reports it cannot resolve the accession |

## Why rung 2 exists

Some submitters' original FASTQs are stored by NCBI as raw "source" objects that never pass through the SRA normalisation pipeline. Neither ENA's mirror nor `prefetch` finds them, yet the Data Locator API lists them with direct download links and md5. Symptom pattern: ENA `fastq_ftp` empty **and** `prefetch` fails to resolve the accession, while `https://trace.ncbi.nlm.nih.gov/Traces/sdl/2/retrieve?acc=<RUN>` returns files of type `source`.

## Reading order and naming

- Source files arrive with the submitter's names (for example `..._R1_001.fastq.gz`). The tool renames them to `RUN_1.fastq.gz`, `RUN_2.fastq.gz`, index reads to `RUN_I1`/`RUN_I2`, so downstream code can use one glob. When it cannot tell the roles apart (no R/I token, several lanes) it keeps the original names and writes `kept_original_names:<reason>` in the `note` column. Look at those rows by hand.
- `.sra` route: `fasterq-dump --split-files` yields `RUN_1.fastq`, `RUN_2.fastq` (and `RUN_3` when technical reads are included). Check which file holds the barcode/UMI read from the read lengths before trusting the numbering.

## Newly released runs

A run that is public in SRA but not yet in ENA usually appears in ENA within days. If time allows, waiting and repeating rung 1 is cheaper than rungs 2 and 3.
