# STARsolo parameters for 10x libraries against a composite reference

The command below is the one that ran on several 10x 5' GEX libraries; the chemistry-dependent parts are in the table. Everything else was identical between chemistries.

```
ulimit -n 100000          # many threads open many files; raise the limit before STAR
STAR --genomeDir INDEX_DIR \
  --readFilesIn R2.fastq.gz R1.fastq.gz --readFilesCommand zcat \   # cDNA read first, barcode read second
  --runThreadN THREADS --limitBAMsortRAM BYTES \
  --soloType CB_UMI_Simple --soloCBwhitelist WHITELIST.txt \
  --soloCBstart 1 --soloCBlen 16 --soloUMIstart 17 --soloUMIlen UMI_LEN \
  --soloBarcodeReadLength 0 \
  --soloFeatures Gene GeneFull Velocyto \
  --soloCBmatchWLtype 1MM_multi_Nbase_pseudocounts --soloUMIdedup 1MM_CR \
  --soloUMIfiltering MultiGeneUMI_CR --soloCellFilter EmptyDrops_CR \
  --soloStrand STRAND \
  --outSAMtype BAM SortedByCoordinate --outSAMattributes NH HI nM AS CR UR CB UB GX GN \
  --outFileNamePrefix OUTDIR/ --outTmpDir FAST_SCRATCH/SAMPLE
```

| Library | Whitelist file used | UMI length | `--soloStrand` |
|---|---|---|---|
| 10x 5' v2 | `737K-august-2016.txt` | 10 | Reverse |
| 10x GEM-X 5' v3 | `3M-5pgex-jan-2023.txt` (3,686,400 barcodes) | 12 | Reverse |
| 10x Multiome, GEX side (3') | `737K-arc-v1.txt` (736,320 barcodes) | 12 | Forward |

Confirm read structure and whitelist against the vendor documentation for your exact kit and version before use; the table records what worked on the source data, not a complete chemistry list. For 3' libraries the usual STARsolo setting is `--soloStrand Forward`.

## Why the pre-flight exists

One batch of libraries was run with the 5' v2 whitelist and a 10 bp UMI although they were GEM-X 5' v3. STARsolo did not fail: "Reads With Valid Barcodes" was 0.018 against 0.71-0.96 for the correctly configured libraries, and only a few hundred cells were called. Cell Ranger's own barcodes for the same libraries were 100% in the GEM-X whitelist and about 0.04-0.06% in the v2 whitelist. `whitelist_preflight.py` on the first 100,000 R1 reads gives the same answer in seconds. Run it for every new library batch, and treat exit code 3 as a stop.

## Operational patterns that avoided re-work

- Skip a sample whose `Log.out` already ends with `ALL DONE!`, and skip one whose FASTQ still has an `.aria2` sidecar (download in flight).
- Before queueing, check whether the same output directory is already queued or running in the job system; a second job would write to the same prefix.
- Put STAR's temporary and BAM-sort files on fast local scratch, with a free-space check, and copy finished output to long-term storage afterwards.
- Queue a script file per sample rather than an inline `bash -c "..."` string in schedulers that re-parse commands.
- Raw barcode reads from SRA via `fasterq-dump` need `--include-technical` for several 10x-style submissions; check which output file holds the 16+10/12 bp barcode read before setting `--readFilesIn`.
