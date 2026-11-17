---
name: spatial-seurat-qc
description: >
  Full Visium HD spatial transcriptomics QC, loading, and preprocessing pipeline in R/Seurat.
  Use this skill whenever the user mentions loading Visium data, spatial QC, spot filtering,
  SCTransform for spatial, SpatiallyVariableFeatures, percent.mt for spatial data,
  ReadVisiumHD, Load10X_Spatial, or any preprocessing step for 10X Genomics spatial data.
  Also trigger when the user asks about normalization strategy for spatial data, spatial
  dimensionality reduction, or clustering of spatial transcriptomics data.
  Always use this skill at the start of any new Visium HD analysis session.
---

# Spatial Seurat QC Skill

End-to-end QC and preprocessing for **10X Genomics Visium HD** data using Seurat.
Produces a clean, normalized `SpatialExperiment`-compatible Seurat object ready for
downstream GSEA, clustering, and visualization.

---

## Workflow Overview

```
Load data → Compute QC metrics → Filter spots → Normalize → Dim reduction → Cluster → Save
```

**Default resolution**: 16µm bins (~131K spots for full colon section)
**Preferred normalization**: SCTransform (handles spatial UMI depth variation)

---

## Step 1 — Load Visium HD Data

```r
library(Seurat)
library(ggplot2)
library(patchwork)
library(dplyr)

# Adjust path to your 10X output directory
data_dir <- "data/raw/Visium_HD_Human_Colon_Cancer_binned_outputs/binned_outputs/square_016um"

visium_obj <- Load10X_Spatial(
  data.dir   = data_dir,
  filename   = "filtered_feature_bc_matrix.h5",
  assay      = "Spatial",
  image      = Read10X_Image(
    image.dir  = file.path(data_dir, "spatial"),
    image.name = "tissue_lowres_image.png"
  )
)

# Quick sanity check
cat("Spots:", ncol(visium_obj), "\n")
cat("Genes:", nrow(visium_obj), "\n")
```

> **Visium HD note**: Use `Load10X_Spatial()` for compatibility. `ReadVisiumHD()` is
> available in Seurat ≥ 5.1 but behaviour varies. Stick with `Load10X_Spatial()` unless
> you specifically need the newer API.

---

## Step 2 — Compute QC Metrics

```r
# Mitochondrial percentage (human: "^MT-", mouse: "^mt-")
visium_obj[["percent.mt"]] <- PercentageFeatureSet(visium_obj, pattern = "^MT-")

# Ribosomal percentage (optional but useful for colon cancer data)
visium_obj[["percent.ribo"]] <- PercentageFeatureSet(visium_obj, pattern = "^RP[SL]")

# Spot complexity ratio
visium_obj[["log10_genes_per_UMI"]] <- log10(visium_obj$nFeature_Spatial) /
                                        log10(visium_obj$nCount_Spatial)
```

### Visualise QC distributions

```r
qc_violin <- VlnPlot(
  visium_obj,
  features = c("nCount_Spatial", "nFeature_Spatial", "percent.mt"),
  pt.size  = 0,
  ncol     = 3
)

qc_spatial <- SpatialFeaturePlot(
  visium_obj,
  features = c("nCount_Spatial", "nFeature_Spatial", "percent.mt"),
  ncol     = 3
)

qc_violin / qc_spatial
```

---

## Step 3 — Filter Spots

Sensible defaults for Visium HD colon cancer. **Always inspect distributions before hardcoding.**

```r
# Inspect quantiles to choose thresholds
quantile(visium_obj$nCount_Spatial,  probs = c(0.01, 0.05, 0.95, 0.99))
quantile(visium_obj$nFeature_Spatial, probs = c(0.01, 0.05, 0.95, 0.99))
quantile(visium_obj$percent.mt,       probs = c(0.90, 0.95, 0.99))

# Filter — adjust thresholds based on your quantile inspection
visium_obj <- subset(
  visium_obj,
  subset = nCount_Spatial   >  100   &
           nCount_Spatial   < 50000  &
           nFeature_Spatial >  50    &
           percent.mt       <  25
)

cat("Spots after filtering:", ncol(visium_obj), "\n")
```

> **Spatial-specific caveat**: Empty tissue areas produce low-count spots. The lower
> `nCount` threshold (100) removes these. The upper threshold removes doublet-like
> artefacts at tissue edges.

---

## Step 4 — Normalise

### Option A: SCTransform (recommended)

```r
# SCTransform accounts for sequencing depth variation across tissue
# vars.to.regress: add "percent.mt" only if mt is spatially confounded
visium_obj <- SCTransform(
  visium_obj,
  assay              = "Spatial",
  vars.to.regress    = "percent.mt",
  verbose            = FALSE,
  return.only.var.genes = FALSE   # keep all genes for GSEA downstream
)
```

### Option B: LogNormalize (faster, good for exploration)

```r
visium_obj <- NormalizeData(visium_obj, assay = "Spatial")
visium_obj <- FindVariableFeatures(visium_obj, nfeatures = 3000)
visium_obj <- ScaleData(visium_obj)
```

---

## Step 5 — Dimensionality Reduction & Clustering

```r
# PCA
visium_obj <- RunPCA(visium_obj, assay = "SCT", verbose = FALSE)
ElbowPlot(visium_obj, ndims = 40)   # choose n_pcs from elbow

n_pcs <- 30   # adjust after inspecting elbow plot

# Neighbours + UMAP
visium_obj <- FindNeighbors(visium_obj, dims = 1:n_pcs, verbose = FALSE)
visium_obj <- FindClusters(visium_obj, resolution = 0.5, verbose = FALSE)
visium_obj <- RunUMAP(visium_obj, dims = 1:n_pcs, verbose = FALSE)

# Visualise clusters spatially
SpatialDimPlot(visium_obj, label = TRUE, label.size = 3) +
  DimPlot(visium_obj, reduction = "umap", label = TRUE)
```

---

## Step 6 — Spatially Variable Features

```r
# Compute spatially variable features (Moran's I based)
# Note: slow on 131K spots — consider subsetting for exploration
visium_obj <- FindSpatiallyVariableFeatures(
  visium_obj,
  assay    = "SCT",
  features = VariableFeatures(visium_obj)[1:1000],  # top variable genes
  selection.method = "moransi"
)

top_svg <- SpatiallyVariableFeatures(visium_obj, selection.method = "moransi")[1:6]
SpatialFeaturePlot(visium_obj, features = top_svg, ncol = 3)
```

---

## Step 7 — Save Object

```r
# Save as .rds for reproducibility
dir.create("data/processed", recursive = TRUE, showWarnings = FALSE)

saveRDS(visium_obj, file = "data/processed/visium_hd_qc_complete.rds")

# Also save QC summary
qc_summary <- data.frame(
  metric = c("initial_spots", "filtered_spots", "genes"),
  value  = c(
    ncol(Read10X_h5(file.path(data_dir, "filtered_feature_bc_matrix.h5"))),
    ncol(visium_obj),
    nrow(visium_obj)
  )
)
write.csv(qc_summary, "data/processed/qc_summary.csv", row.names = FALSE)

message("Object saved: data/processed/visium_hd_qc_complete.rds")
```

---

## Quick Reference: Key Seurat Functions for Visium HD

| Task                        | Function                          |
|-----------------------------|-----------------------------------|
| Load data                   | `Load10X_Spatial()`               |
| Compute QC metrics          | `PercentageFeatureSet()`          |
| Normalise                   | `SCTransform()` / `NormalizeData()`|
| Spatially variable genes    | `FindSpatiallyVariableFeatures()` |
| Visualise on tissue         | `SpatialFeaturePlot()`, `SpatialDimPlot()` |
| Save / load                 | `saveRDS()` / `readRDS()`         |

---

## Performance Tips for Large Visium HD (~131K spots)

- Run `FindSpatiallyVariableFeatures()` on a gene subset (top 1000–3000) — full run is very slow
- `SCTransform()` with `ncells = 5000` (subsampling) speeds up model fitting with minimal accuracy loss
- Use `future` parallelism: `plan("multicore", workers = 4)` before SCTransform
- Cache `.rds` aggressively — reload rather than rerun QC each session

```r
# Parallel SCTransform
library(future)
plan("multicore", workers = 4)
options(future.globals.maxSize = 8000 * 1024^2)  # 8 GB RAM limit

visium_obj <- SCTransform(visium_obj, assay = "Spatial", verbose = FALSE)
```

---

## Reference Files

- `references/extended-qc-plots.R` — additional diagnostic plots (doublet scoring, ambient RNA)
