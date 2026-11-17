# What each check means and what to do about it

| Check | Severity | Meaning | Action |
|---|---|---|---|
| zero-byte, incomplete-download | ERROR | Transfer did not finish or produced an empty file | Re-fetch; with `sra-ena-geo-download` re-run the fetch stage and verify |
| gzip-corrupt | ERROR | Truncated or damaged compressed file | Re-fetch; do not analyse a partial FASTQ (reads silently missing) |
| md5, size, missing-file | ERROR | File differs from the provider's checksum/size or is absent | Re-fetch; if it persists, check the provider's checksum list is for the same release |
| identical-content | WARN | Two files with the same bytes | Check for a copy or a duplicated sample |
| mate-count, mate-names | ERROR | R1/R2 not in sync | Re-download both mates; never trim or align out-of-sync pairs |
| fastq-structure | ERROR | Malformed record, sequence/quality length differ, truncated final record | Re-fetch or regenerate from the BAM/SRA |
| unpaired | WARN | Only one mate found | Confirm single-end design or find the missing mate |
| dimensions | ERROR | Matrix size matches neither (genes x cells) nor its transpose | Wrong annotation files or a modified matrix |
| orientation | OK/WARN | WARN when the layout is not the usual one for the platform | Transpose deliberately in the reader (see `parse-vs-10x-qc`), do not guess |
| non-integer | ERROR (with `--expect counts`) | Normalised/scaled values | Find the raw counts; many tools (DESeq2, scDblFinder, beta-binomial QC) require integers |
| nnz, index-range, negative-values | ERROR | Truncated or edited matrix file | Re-fetch |
| duplicate-gene-ids / cell-ids | ERROR | Ids not unique | Fix upstream; collapsing by name hides it |
| mixed-species-ids | WARN | Several Ensembl species prefixes | Expected for a composite reference; unexpected otherwise |
| empty-cells | WARN | More than half of the barcodes have zero counts | Probably an unfiltered matrix; filter before using the cell count |
| replicates | WARN | A group has fewer than `--min-n` units | Report as descriptive only; do not run tests that assume replicates |
| pseudo-replication | WARN | Many rows from one unit | Aggregate to the unit (pseudobulk) or model the unit as a random effect |
| confounded | ERROR | Two factors coincide level by level | The effects cannot be separated; redesign or restrict claims |
| nested | WARN | A factor occurs inside one level of another | Effect of the nested factor cannot be estimated within the other |

Limits: the audit reads headers and counts, it does not judge biological plausibility; the FASTQ scan is sequential and can be slow on very large files (use `--max-reads`); matrix checks hold per-cell sums in memory (a few hundred MB for millions of cells).
