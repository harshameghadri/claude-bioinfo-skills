---
name: stepwise-cluster-labelling
description: "Classical, manual cell-type labelling of single-cell, single-nucleus or imaging-panel (Xenium, CosMx, MERFISH) data, for any tissue. Seurat workflow: per-sample RPCA integration, cluster, downsampled per-cluster markers, explicit naming of multiplet and low-quality ('Trash') clusters, lineage subset and recluster in 2-3 purification rounds, fine labels from markers, unity-scaled per-subject marker heatmap. Use for de novo annotation, as a fallback or concordance check for label transfer, or when the user asks to label clusters 'the classical way'."
---

# Stepwise cluster labelling (classical, tissue-agnostic)

The procedure is a classical, manual annotation method for snRNA-seq atlases. It is dataset-agnostic: nothing here is
specific to lung or any other tissue. Every tissue-specific choice (lineages, marker genes, thresholds)
is an INPUT the user supplies or confirms at a decision point. Do not hard-code it.

Helpers in `kernel.R` load with this skill (R kernel, Seurat >= 4; tested on Seurat 5):
`rpca_integrate_by_sample()`, `markers_per_cluster()`, `cluster_review_table()`,
`apply_cluster_names()`, `unity_heatmap_matrix()`, `unity_heatmap()`.

## Inputs to collect first (decision point 0)

Ask for, or confirm, the following before running anything:
1. Object, sample column (e.g. `orig.ident`), disease/group column, count column (`nCount_RNA`, or nuclear counts for imaging data).
2. Lineage marker list for the tissue, as a named list (e.g. `list(Endothelial = c("PECAM1","CDH5","VWF"), Immune = c("PTPRC"), Epithelial = c("EPCAM"), Stromal = c("COL1A1","DCN"))`). For an imaging panel, keep only genes on the panel and say which classical markers are off panel.
3. Reference marker tables, if any exist (e.g. a DOR or FindAllMarkers table per reference cell type). These are used to compare clusters with known types.
4. Whether integration is wanted. Default: RPCA by sample. Exception: if sample = patient = disease group (e.g. one core per patient on a TMA), integration can remove the biology. Then also run unintegrated (and optionally Harmony), and compare the state shares per sample across settings.

## Round structure

```
Round 0  whole object  -> rough lineage labels + named multiplet/Trash clusters
Round 1  each lineage  -> subset, recluster, name multiplet/Trash clusters again, provisional fine labels
Round 2  each lineage  -> drop the named multiplet/Trash clusters, recluster (often fewer PCs), final fine labels
(Round 3 only if Round 2 still shows mixed clusters; 2-3 rounds are normally enough)
```

The owner reviews the cluster table after every round. Do not finalise labels without that review.

## Per round

1. **Integrate** (`rpca_integrate_by_sample`): split by sample; per sample NormalizeData, FindVariableFeatures (vst);
   SelectIntegrationFeatures; per sample ScaleData (regress the count column) and RunPCA; FindIntegrationAnchors
   (reduction = "rpca", dims 1:30, k.filter below the smallest sample); IntegrateData. On a targeted panel
   (a few hundred genes), use all panel genes as features. For > ~300k cells, integrate a sketch (Seurat v5
   SketchData + IntegrateLayers(RPCAIntegration)) and project to all cells; say which route was used.
2. **Reduce and cluster**: ScaleData, RunPCA(50). Choose dims with ElbowPlot and DimHeatmap (whole object or
   lineage: ~1:30-50; late-round, small lineages: often ~1:8-15). Then FindNeighbors, FindClusters
   (resolution 1-3; over-cluster rather than under-cluster), RunUMAP.
3. **Markers** (`markers_per_cluster`): downsample to 500 cells per cluster; FindMarkers(ident.1 = cluster,
   only.pos = TRUE, logfc.threshold = 0.1) for each cluster, in parallel. Use the RNA assay, not the integrated one.
4. **Review table** (`cluster_review_table`): per cluster, n cells, median counts, share per sample, top
   markers, mean expression of each lineage marker set, and two suggestions to check by eye:
   - `mixed_lineage`: a second lineage scores at least `mix_ratio` of the top lineage, or appears among the top
     markers. These are multiplets in droplet data, or segmentation errors / transcript spillover in imaging data.
   - `low_quality`: median counts below `low_q` of the object median.
   Also check that a cluster is not driven by one sample (share per sample).
5. **Name every cluster** (`apply_cluster_names`): a named vector of cluster -> label. Junk gets explicit names
   such as `Fibro_EC_Multiplets`, `Epi_EC_Multiplets`, `T_EC_Multiplets`, `AT2_Multiplet`, `Trash`.
   Junk clusters are kept and labelled, then excluded at the next round; they are not silently deleted.
6. **Subset** the lineage for the next round with `subset(obj, subset = <label_col> %in% keep)`.

## Doublets

- **Droplet data:** run scDblFinder (or DoubletFinder) per sample as a diagnostic. The decision still rests on the
  named mixed clusters.
- **Imaging data (Xenium etc.):** droplet doublets do not exist. The analogue is segmentation error and
  transcript spillover between neighbouring cells. Prefer nucleus-only counts where the platform provides them,
  apply the same mixed-lineage naming, and report doublet scores only as a diagnostic.

## Fine labels

Fine labels come from markers: compare each cluster's top markers with the reference marker tables
(overlap, or mean expression of each reference set). Name a disease-associated state only when its marker block
is clearly the cluster's strongest. Then check that its frequency per subject differs between groups: frequency
first, DE only if wanted.

## Unity heatmap check (final step, and for label-transfer comparisons)

`unity_heatmap_matrix()` builds pseudobulk means per cell type x group x subject (only combinations with
>= `min_cells` cells; the default is 5), and scales each gene to 0-1 across columns ((x - min) / (max - min)). Gene rows follow a curated
order grouped by cell type, with no row or column clustering. Columns are ordered by cell type, then group,
then subject. `unity_heatmap()` draws it with ComplexHeatmap: columns split by cell type, top annotation =
cell type, group, subject. To compare two annotations (e.g. de novo vs label transfer, or query vs reference),
draw two heatmaps with the same gene rows side by side.

## Reporting

- Per round: the review table, the naming map, the cells set aside per junk label, and the cell count kept.
- Final: labels per cell, the confusion matrix and ARI against any other annotation, the unity heatmap, and the
  per-subject frequency table.
- State the deviations: sketch vs full object, integration setting, dims and resolution per round.
- Integration sensitivity: when the supplement needs it, rerun the final round with Harmony and show that the
  labels and conclusions do not change (confusion matrix).
