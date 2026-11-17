---
name: parse-vs-10x-qc
description: Cell-level QC for single-cell RNA-seq count matrices from Parse Evercode (split-pipe) and 10x Genomics (Cell Ranger), alone or mixed. Reads both layouts (Parse cells x genes vs 10x genes x cells), applies MAD floors on depth and genes, a beta-binomial test for excess mitochondrial protein-coding reads instead of a fixed percent.mt, a top-gene/MALAT1 rule, a Parse round-1 well-contamination screen, depth thinning and optional doublet calls. Use for scRNA-seq QC thresholds, Parse vs 10x comparisons, split-pipe output, percent.mt cut-offs, well spikes.
---

# Parse vs 10x single-cell QC

Fixed cut-offs such as `percent.mt < 10` or `nFeature > 200` do not transfer between platforms: Parse and 10x differ in depth, in mitochondrial and ncRNA capture and in how a dataset is split into wells. This skill reads both formats into one structure and applies data-driven rules whose thresholds are reported, so the result can be defended and reproduced.

Requirements: R with `Matrix`, `data.table`, `VGAM`. Optional: Bioconductor `scDblFinder` + `SingleCellExperiment` (doublets only). Run `Rscript scripts/run_qc.R --help`. Paths are relative to this skill folder.

## Procedure

1. **Locate inputs.** Parse: the `DGE_filtered` (or unfiltered) folder of each sample with `count_matrix.mtx(.gz)`, `all_genes.csv(.gz)`, `cell_metadata.csv(.gz)`. 10x: the `filtered_feature_bc_matrix` folder (`matrix.mtx`, `barcodes.tsv`, `features.tsv`, gzipped or not). Decide a sample name per folder and, if samples belong to the same biological source, a pool label (thresholds are fitted per pool; one pool by default).
2. **Run QC.**
   `Rscript scripts/run_qc.R --parse S1=/path/S1/DGE_filtered --parse S2=/path/S2/DGE_filtered --10x S3=/path/S3/filtered_feature_bc_matrix --outdir qc_out [--species human|mouse] [--sensitivity] [--thin-target auto] [--save-rds]`
   Add `@POOL` to an input (`S1=/path@lineA`) to fit thresholds per pool. Mixed platforms are allowed; samples are restricted to shared gene ids (a message says so). Exit codes: 0 ok, 1 error, 2 usage.
3. **Read `thresholds.tsv` and `sample_summary.tsv` before using any flag.** Check that the depth and gene floors are plausible for the assay, that `mt_rho` (overdispersion) is small and sensible, and that `pct_pass` is not driven by one rule. The tables are the record of what was applied.
4. **Apply the flags** in `cell_qc.tsv`: keep `qc_pass`. The columns `qc_depth`, `qc_genes`, `qc_mt`, `qc_top` say why a cell failed. Covariates (`frac_mtrrna`, `RN7SK_frac`, `RMRP_frac`, `RPPH1_frac`, `histone_frac`, `complexity`) are for inspection and for regression or colouring, not filters.
5. **Parse only: read `well_spikes.tsv`.** Each row is a gene strongly enriched in one round-1 well relative to the other wells of the same sample (a well-specific contamination or carry-over signature). Decide per case whether to drop the gene from analysis or the well's cells; the screen only reports.
6. **Optional doublets.** `--thin-target auto --save-rds` writes `thinned_counts.rds` and `qc_counts.rds`; then `Rscript scripts/doublets_scdblfinder.R --qc-rds qc_out/qc_counts.rds --thinned-rds qc_out/thinned_counts.rds --outdir qc_out/doublets`. Compare native and thinned doublet rates (see rules below). Exit 3 means scDblFinder is not installed.
7. **Report.** State platform(s), pool structure, the thresholds table, pass rates per sample and which rules removed cells.

## Rules (defaults; every one is an option)

| Rule | Default | Meaning |
|---|---|---|
| Analysis matrix | mt-rRNA (MT-RNR1/2) removed | counted before depth/genes/top-gene, still reported as `frac_mtrrna` of raw UMIs |
| Depth / genes | median - 4 MAD of log10 values, pooled | `--mad-k` |
| Mitochondrial | beta-binomial upper tail <= 0.001 on mt protein-coding UMIs given cell UMIs | no fixed percent.mt; `--mt-alpha` |
| Top gene | one gene > 20% of UMIs | not flagged if it is MALAT1 and complexity is within 2 MAD of the median; `--top-frac` |
| Well screen (Parse) | fold change >= 5 and log10 p < -20, exact one-sided binomial vs other wells of the same sample | `--spike-fc`, `--spike-log10p` |
| Sensitivity | per-sample 3 MAD flags `v1_*` | stored, never applied; `--sensitivity` |

## Rules that prevent known failures

- **Orientation.** Parse `count_matrix` is cells x genes, 10x is genes x cells. The readers decide from the annotation sizes and refuse square or inconsistent matrices; never transpose by assumption.
- **Beta-binomial fit.** The method-of-moments overdispersion is not robust: a few percent of high-mt cells inflate it until nothing is flagged. The fit therefore starts without cells above median + 5 MAD of the mt fraction and is refitted without flagged cells (`mt_fit_rounds`, `mt_fit_cells` in `thresholds.tsv`). This hardening is part of this skill's implementation and is tested with planted cells; check `mt_rho` on real data.
- **Pooled thresholds.** Pooling samples that differ strongly in depth makes the floors reflect the mixture. Pool only samples that should be comparable.
- **Doublets are informational.** Doublet scores follow sequencing depth. Compare calls on native counts with calls after thinning to a common depth: if native calls fall towards zero after thinning they were a depth effect. Do not filter cells on doublet calls without that check, and do not quote a platform "doublet rate" from another dataset.
- **Seurat v5.** After merging objects built from these matrices call `JoinLayers()` before downstream steps.
- **Missing optional package.** The mitochondrial rule needs `VGAM`; without it the run stops with an error rather than skipping the rule.

## Outputs

`cell_qc.tsv` (one row per cell, all metrics and flags), `thresholds.tsv`, `sample_summary.tsv`, `well_spikes.tsv` + `well_spikes_summary.tsv` (Parse), optional `thinned_counts.rds`, `qc_counts.rds`, `doublets/`.

## Testing

`bash tests/run.sh` (60 tests, synthetic matrices generated on the fly, no network, no real data). Planted problems must be found (low depth 10/10, high mt 10/10, top gene 5/5, one well spike), MALAT1-dominated cells must not be flagged, the readers must reproduce the simulated counts exactly. The `scDblFinder` code path is not exercised by the tests (only its argument handling and the missing-package exit code); it is optional. Details and the rationale for each rule: `references/parse-vs-10x.md`.
