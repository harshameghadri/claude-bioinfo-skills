# Templates Reference

All templates in this file are designed for single-cell bioinformatics projects on Mac (local + GCS), using R/renv, qmd, and Notion for documentation.

---

## Section: .gitignore

```gitignore
# ── R & RStudio ─────────────────────────────────────────────────────────────
.Rproj.user/
.Rhistory
.RData
.Ruserdata
*.Rcheck/

# ── renv ────────────────────────────────────────────────────────────────────
renv/library/
renv/staging/
renv/python/

# ── Large biological objects (NEVER commit these) ────────────────────────────
*.rds
*.RDS
*.h5seurat
*.h5ad
*.loom
*.h5
*.hdf5

# ── Raw and processed data (document paths in DATA_REGISTRY.md instead) ─────
data/raw/
data/processed/
results/objects/

# ── Rendered outputs (regenerated from qmd) ──────────────────────────────────
reports/

# ── Credentials and secrets ──────────────────────────────────────────────────
.env
*.env
secrets/
*_token*
*_key.txt
*_api_key*
.gcs_credentials*
service_account*.json

# ── macOS artifacts ──────────────────────────────────────────────────────────
.DS_Store
.AppleDouble
.LSOverride
Thumbs.db

# ── Quarto / knitr cache ─────────────────────────────────────────────────────
*_cache/
*_files/
.quarto/

# ── Python (if used for secondary analysis) ──────────────────────────────────
__pycache__/
*.py[cod]
.venv/
*.egg-info/
```

---

## Section: manifest.yml

```yaml
project:
  name: "{project_name}"
  created: "{YYYY-MM-DD}"
  status: active
  hypothesis: >
    {One-to-three sentence biological hypothesis or research question.}

experiment:
  platform:
    - "{10X Flex / Parse / other}"
  cell_lines:
    - "{cell_line_1}"
  backgrounds:
    - "{WT}"
    - "{DrugB-Resistant}"
  treatments:
    - "{-ve}"
    - "{DrugA (72h)}"
  n_samples: {integer}
  multi_batch: {true/false}

data:
  metadata: "data/metadata/sample_metadata.csv"
  raw_data_registry: "data/raw/DATA_REGISTRY.md"
  gcs_bucket: "gs://{bucket_name}/{project_name}/"
  large_objects_local: "~/Data/{project_name}/objects/"

documentation:
  notion_journal: "{https://notion.so/...}"
  decision_logs: "docs/decisions/"

reproducibility:
  r_version: "{R version at project start}"
  renv_lockfile: "renv.lock"
```

---

## Section: README

```markdown
# {project_name}

> {One-sentence project tagline}

## Hypothesis

{Full biological hypothesis from manifest.yml — 2–3 sentences.}

## Sample Overview

| Sample ID | Cell Line | Background | Treatment | Platform |
|---|---|---|---|---|
| {LineA_WT_Ctrl} | {CellLineA} | {WT} | {-ve} | {10X Flex} |
| ... | | | | |

## Technology

- **Platform:** {10X Flex / Parse / ...}
- **Analysis language:** R {version}
- **Environment management:** renv (see `renv.lock`)

## Project Structure

```
scripts/     Analysis scripts (numbered by phase)
data/        Metadata (tracked); raw data paths in DATA_REGISTRY.md
results/     Figures and tables
docs/        Decision logs per analytical checkpoint
reports/     Rendered HTML reports (gitignored; regenerated from scripts)
```

## Reproducibility

To restore the R environment:
```r
install.packages("renv")
renv::restore()
```

## Data Access

Raw data and large objects are stored outside this repository.
See `data/raw/DATA_REGISTRY.md` for all paths.

GCS bucket: `gs://{bucket_name}/{project_name}/`

## Notion Journal

Full analysis narrative and decision log: {notion_url}

## Status

{Active / Analysis complete / Manuscript submitted}

---
*Last updated: {date}*
```

---

## Section: 00_setup.R

```r
# ============================================================
# 00_setup.R
# {project_name} — Shared setup script
# Source this at the top of every analysis script.
# ============================================================

# ── Package loading ──────────────────────────────────────────
library(Seurat)
library(dplyr)
library(ggplot2)
library(patchwork)
library(readr)
library(tibble)
library(stringr)
library(RColorBrewer)
# Add platform-specific packages:
# library(BPCells)       # for large 10X datasets
# library(harmony)       # if multi-batch integration
# library(scDblFinder)   # doublet detection

# ── Project paths ────────────────────────────────────────────
BASE_DIR       <- here::here()          # Project root (works via .Rproj)
DATA_DIR       <- file.path(BASE_DIR, "data")
METADATA_DIR   <- file.path(DATA_DIR, "metadata")
PROCESSED_DIR  <- file.path(DATA_DIR, "processed")
RESULTS_DIR    <- file.path(BASE_DIR, "results")
FIGURES_DIR    <- file.path(RESULTS_DIR, "figures")
OBJECTS_DIR    <- file.path(RESULTS_DIR, "objects")
REPORTS_DIR    <- file.path(BASE_DIR, "reports")
DOCS_DIR       <- file.path(BASE_DIR, "docs")

# GCS paths (update with actual bucket)
GCS_BUCKET     <- "gs://{bucket_name}/{project_name}"
GCS_OBJECTS    <- file.path(GCS_BUCKET, "objects")

# ── Metadata ─────────────────────────────────────────────────
sample_metadata <- readr::read_csv(
  file.path(METADATA_DIR, "sample_metadata.csv"),
  show_col_types = FALSE
)

# ── Color palettes ───────────────────────────────────────────
# Adapt to actual groups in the project
PALETTE_BACKGROUND <- c(
  "WT"                   = "#4E79A7",
  "DrugB-Resistant" = "#F28E2B"
)

PALETTE_TREATMENT <- c(
  "-ve"               = "#BAB0AC",
  "DrugA (72h)"        = "#E15759",
  "DrugB (72h)" = "#76B7B2",
  "DrugA+DrugB"  = "#59A14F",
  "DrugA inhibitor"    = "#EDC948"
)

PALETTE_CELL_LINE <- c(
  "CellLineA" = "#B07AA1",
  "CellLineB"   = "#FF9DA7"
)

# ── ggplot2 theme ────────────────────────────────────────────
theme_sc <- function() {
  theme_bw(base_size = 12) +
    theme(
      panel.grid.minor = element_blank(),
      strip.background = element_rect(fill = "grey95"),
      legend.position  = "right"
    )
}
theme_set(theme_sc())

# ── Reproducibility ──────────────────────────────────────────
set.seed(42)
options(future.globals.maxSize = 8000 * 1024^2)  # 8 GB for parallelism

cat("✓ Setup complete:", format(Sys.time(), "%Y-%m-%d %H:%M"), "\n")
cat("  R version:", R.version.string, "\n")
cat("  Samples loaded:", nrow(sample_metadata), "\n")
```

---

## Section: qmd header

```{=markdown}
---
title: "{Checkpoint Name} — {project_name}"
subtitle: "Phase {nn}: {Brief description}"
author: "Your Name"
date: "`r Sys.Date()`"
format:
  html:
    toc: true
    toc-depth: 3
    toc-float: true
    code-fold: true
    code-tools: true
    embed-resources: true
    theme: flatly
    fig-width: 10
    fig-height: 7
execute:
  warning: false
  message: false
  cache: false
---

```{r setup, include=FALSE}
source("../00_setup.R")
```

## Overview

**Checkpoint:** Phase {nn} — {checkpoint name}  
**Date:** `r Sys.Date()`  
**Input:** {describe input object or data}  
**Output:** {describe expected output objects and figures}  
**Decision log:** `docs/decisions/{nn}_{checkpoint}_decisions.md`
```

---

## Section: Decision Log

```markdown
# Decision Log — Phase {nn}: {Checkpoint Name}

**Project:** {project_name}  
**Date:** {YYYY-MM-DD}  
**Script:** `scripts/{nn}_{checkpoint}/{nn}_{checkpoint}.qmd`

---

## Decision Made

{Exact parameters, thresholds, or method selected.}

Example:
- nFeature_RNA: 200 – 6,000
- percent.mt: < 15%
- Doublet removal: scDblFinder (expected_doublets = 0.08)
- Cells retained: {n} / {total} ({pct}%)

## Rationale

{Data-driven or biological justification for this decision.}

## Alternatives Considered and Rejected

| Alternative | Reason Rejected |
|---|---|
| {percent.mt < 20} | {Too permissive; {n} contaminated cells passed in pilot} |
| {nFeature < 8000} | {Retained likely multiplets in LineA_Resist sample} |

## Outputs Produced

| Type | Path |
|---|---|
| Seurat object | `results/objects/{project}_{nn}_seu_filtered_{date}.rds` |
| QC violin plot | `results/figures/{nn}_qc/fig01_violin_qc_metrics.pdf` |
| Per-sample summary | `results/tables/01_qc_cell_counts.csv` |

## Open Flags

- [ ] {Flag 1: e.g., LineA_Resist sample has unusually high ambient RNA — revisit after SoupX}
- [ ] {Flag 2: ...}

---
*Logged by: Your Name | {date}*
```
