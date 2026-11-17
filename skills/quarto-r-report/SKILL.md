---
name: quarto-r-report
description: >
  Generate professional, reproducible Quarto (.qmd) HTML reports for spatial transcriptomics
  and single-cell analysis in R. Use this skill whenever the user wants to create a Quarto
  report, .qmd file, HTML analysis report, or embed Seurat/spatial plots in a reproducible
  document. Also trigger when the user mentions: rendering to HTML, Quarto YAML headers,
  code chunk options, embedding interactive plotly in Quarto, self-contained HTML, or
  combining multiple analysis steps into a polished report. Also use when producing
  any deliverable .qmd analysis report.
---

# Quarto R Report Skill

Produces **professional, self-contained HTML reports** for spatial GSEA analysis.
Reports are designed to be portfolio-ready: clean layout, interactive plots, reproducible
code, and clear narrative structure.

---

## Anatomy of a Report

```
reports/
├── 01_qc_report.qmd          ← QC and data loading
├── 02_gsea_results.qmd       ← Core analysis
├── 03_spatial_viz.qmd        ← Visualization showcase
└── _quarto.yml               ← Shared project config (optional)
```

---

## Step 1 — Standard YAML Header

Use this as the template for every `.qmd` file in the project.

```yaml
---
title: "Spatial GSEA Analysis — [Section Name]"
subtitle: "Visium HD Human Colon Cancer · 16µm resolution"
author: "Your Name"
date: today
date-format: "D MMMM YYYY"

format:
  html:
    theme: flatly               # clean professional theme
    toc: true                   # table of contents
    toc-depth: 3
    toc-location: left
    toc-title: "Contents"
    number-sections: true
    code-fold: true             # collapsible code blocks
    code-summary: "Show code"
    code-tools: true            # copy button + show-all-code
    embed-resources: true       # self-contained single HTML file
    fig-width: 10
    fig-height: 7
    fig-dpi: 150
    df-print: paged             # paginated data frame display

execute:
  echo: true
  warning: false
  message: false
  cache: true                   # cache heavy computations

knitr:
  opts_chunk:
    comment: "#>"
---
```

> **`embed-resources: true`** replaces the older `self-contained: true` in Quarto ≥ 1.3.
> Use it for portable single-file output you can share without a server.

---

## Step 2 — Setup Chunk

Always the first code chunk — loads libraries and sets global theme.

````qmd
```{r}
#| label: setup
#| cache: false       # never cache setup chunk

library(Seurat)
library(ggplot2)
library(patchwork)
library(plotly)
library(dplyr)
library(here)

# Project-wide ggplot theme
theme_spatial <- function(...) {
  theme_minimal(base_size = 12) +
    theme(
      plot.title    = element_text(face = "bold", size = 14),
      plot.subtitle = element_text(colour = "grey50"),
      legend.position = "right",
      ...
    )
}
theme_set(theme_spatial())

# Load the pre-processed Seurat object
visium_obj <- readRDS(here("data/processed/visium_hd_qc_complete.rds"))

cat("Object loaded:", ncol(visium_obj), "spots ×", nrow(visium_obj), "genes\n")
```
````

---

## Step 3 — Section Structure Templates

### QC Report Section

````qmd
## Quality Control {#sec-qc}

Summary of spot-level QC metrics before and after filtering.

```{r}
#| label: fig-qc-violin
#| fig-cap: "QC metrics across all tissue spots. Red dashed lines indicate filter thresholds."
#| fig-width: 12
#| fig-height: 5

VlnPlot(
  visium_obj,
  features = c("nCount_Spatial", "nFeature_Spatial", "percent.mt"),
  pt.size  = 0,
  ncol     = 3
)
```

### Spatial distribution of QC metrics

```{r}
#| label: fig-qc-spatial
#| fig-cap: "Spatial distribution of library size and complexity across tissue."
#| fig-width: 14
#| fig-height: 5

SpatialFeaturePlot(
  visium_obj,
  features = c("nCount_Spatial", "percent.mt"),
  ncol     = 2
)
```
````

### Interactive Plotly Section

````qmd
## Cluster UMAP {#sec-umap}

```{r}
#| label: fig-umap-interactive
#| fig-cap: "Interactive UMAP coloured by Seurat cluster."

# Build ggplot, convert to plotly for interactivity
p <- DimPlot(visium_obj, reduction = "umap", label = TRUE, pt.size = 0.5) +
  theme_spatial() +
  ggtitle("UMAP — Seurat clusters")

ggplotly(p, tooltip = c("colour")) %>%
  layout(legend = list(title = list(text = "Cluster")))
```
````

### Tabbed Results Section

````qmd
## GSEA Results {#sec-gsea}

::: {.panel-tabset}

### Hallmark Pathways

```{r}
#| label: tbl-hallmark
# ... hallmark results table
```

### KEGG Pathways

```{r}
#| label: tbl-kegg
# ... KEGG results table
```

### GO Biological Process

```{r}
#| label: tbl-gobp
# ... GO results table
```

:::
````

### Callout Boxes

````qmd
::: {.callout-note}
## Interpretation
SCTransform normalisation was applied prior to dimensionality reduction.
Mitochondrial percentage was regressed out.
:::

::: {.callout-warning}
## Data limitation
The `molecule_info.h5` file was not available in this dataset version.
Subcellular resolution analysis was therefore not performed.
:::

::: {.callout-tip}
## Reproducibility
All outputs can be regenerated with `quarto render reports/01_qc_report.qmd`.
:::
````

---

## Step 4 — Large / Slow Computations with Caching

```yaml
# Per-chunk cache override — cache the slow bits independently
```

````qmd
```{r}
#| label: sctransform
#| cache: true
#| cache-vars: visium_obj   # only invalidate if this object changes

visium_obj <- SCTransform(visium_obj, assay = "Spatial", verbose = FALSE)
```
````

> **Cache invalidation rule**: Quarto caches based on chunk content hash. If you change
> code in the chunk, it reruns. Rename the label to force a fresh run.

---

## Step 5 — Embed a Summary Table

```r
# Paginated, sortable table with DT
library(DT)

datatable(
  gsea_results_df,
  filter    = "top",
  rownames  = FALSE,
  options   = list(pageLength = 15, scrollX = TRUE),
  caption   = "GSEA results — all pathways with FDR < 0.05"
)
```

---

## Step 6 — Render from R Console

```r
# Render a single report
quarto::quarto_render("reports/01_qc_report.qmd")

# Render all reports in order
report_files <- list.files("reports", pattern = "\\.qmd$", full.names = TRUE)
purrr::walk(sort(report_files), quarto::quarto_render)

# Preview with live reload (development)
quarto::quarto_preview("reports/01_qc_report.qmd")
```

---

## Step 7 — Project-Level `_quarto.yml` (optional)

When you have multiple reports sharing settings:

```yaml
# _quarto.yml — placed in project root
project:
  type: website
  output-dir: docs            # output to docs/ for GitHub Pages

website:
  title: "Spatial GSEA Heatmaps"
  navbar:
    left:
      - href: reports/01_qc_report.qmd
        text: "QC"
      - href: reports/02_gsea_results.qmd
        text: "GSEA"

format:
  html:
    theme: flatly
    embed-resources: false    # false for multi-page sites
    toc: true
```

```bash
# Render the whole site
quarto render
```

---

## Quick Reference: Chunk Options

| Option            | Purpose                                    | Default |
|-------------------|--------------------------------------------|---------|
| `echo: false`     | Hide code, show output only                | true    |
| `eval: false`     | Show code, don't run                       | true    |
| `cache: true`     | Cache this chunk's result                  | false   |
| `fig-width`       | Figure width in inches                     | 7       |
| `fig-height`      | Figure height in inches                    | 5       |
| `fig-cap`         | Figure caption (enables cross-referencing) | —       |
| `label`           | Chunk ID — use `fig-*` or `tbl-*` prefix  | —       |
| `include: false`  | Run chunk but hide code AND output         | true    |

---

## Reference Files

- `references/report-template.qmd` — full copy-paste starter `.qmd` for QC reports
