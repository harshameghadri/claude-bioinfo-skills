# Parse vs 10x: background for the QC rules

## Input layouts

| | Parse Evercode (split-pipe) | 10x (Cell Ranger) |
|---|---|---|
| Matrix file | `count_matrix.mtx(.gz)`, **cells x genes** | `matrix.mtx(.gz)`, **genes x cells** |
| Genes | `all_genes.csv(.gz)` with `gene_id`, `gene_name` (plus genome) | `features.tsv(.gz)`: id, name, type (older: `genes.tsv`) |
| Cells | `cell_metadata.csv(.gz)`; `bc_wells` (barcode combination plus `__sublibrary`), `bc1_well` (round-1 well) | `barcodes.tsv(.gz)` |
| Extra feature types | not applicable | filtered by `feature_type` (default Gene Expression) |

`bc_wells` is unique per cell within a sample; the readers build `cell_id = <sample>_<bc_wells>` (Parse) or `<sample>_<barcode>` (10x). A pipeline-supplied `sample` column in the Parse metadata is kept as `parse_sample` so it cannot collide with the sample label you pass in.

## Why these rules

- **No fixed percent.mt.** The mitochondrial fraction scales with cell type, protocol and depth. The beta-binomial describes how many mt protein-coding UMIs a cell of a given depth is expected to have if its mt fraction varies as in the dataset; cells in the extreme upper tail are flagged. Zero-mt cells are never flagged. The rule targets mt protein-coding genes; mt-rRNA is removed beforehand so that high or variable rRNA capture does not dominate depth.
- **MAD on log10.** Depth and detected genes are roughly log-normal; the floor is median - k MAD with k = 4 (conservative: removes clear failures only). The upper side is not trimmed here because high depth is not a quality failure; use doublet information for that.
- **Top gene and MALAT1.** A cell dominated by one gene is usually a failure (ambient or lysed-cell signature), but MALAT1 is legitimately very high in many nuclei-rich or low-complexity-but-healthy cells. MALAT1-dominated cells are kept when their complexity (log10 genes / log10 UMIs) is typical.
- **Well screen.** In combinatorial-barcoding data the round-1 well is a physical sample unit. A gene that is enormously enriched in one well against the other wells of the same sample (exact binomial plus fold change with a +0.5 pseudocount) points at well-specific carry-over or contamination. Because many genes are tested the p threshold is deliberately extreme.
- **Thinning.** Binomial thinning (each UMI kept with probability target / cell UMIs; cells below the target unchanged) puts cells on a common depth. It is used to separate depth effects from signal, for example for doublet calls.

## Interpreting `thresholds.tsv`

- `umi_floor`, `genes_floor`: the values below which a cell fails depth/genes.
- `mt_pooled_fraction`, `mt_rho`, `mt_shape1/2`: the beta-binomial null actually used; `mt_chi2` is the Pearson statistic. Rho near 0 means mt counts behave binomially; rho > 0.1 on a clean dataset deserves a look.
- `mt_fit_rounds` > 0 means flagged cells were removed and the null refitted.

## Known limits

- Thresholds were designed on Parse data and checked here on synthetic matrices; on a new assay inspect the tables before trusting pass rates.
- Ambient RNA is not modelled. Use a dedicated tool if it matters.
- The doublet script is optional and its scDblFinder call is not covered by the offline tests.
