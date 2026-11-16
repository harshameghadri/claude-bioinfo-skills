# Folder Structure Reference

## Full Annotated Tree

```
{project_name}/
│
├── README.md                           # Human-readable project overview (auto-generated from metadata)
├── manifest.yml                        # Machine-readable project metadata and data registry links
├── {project_name}.Rproj               # RStudio project file (commit this)
├── .gitignore                          # Comprehensive bioinformatics-appropriate exclusions
├── renv.lock                           # Frozen R package versions (ALWAYS commit after changes)
├── .Rprofile                           # renv activation hook (ALWAYS commit)
├── renv/                               # renv internals — only renv.lock and .Rprofile are committed
│
├── data/
│   ├── raw/
│   │   └── DATA_REGISTRY.md           # Canonical record of where raw data lives (GCS URIs, local paths)
│   │                                   # Never commit raw data files — only this registry document
│   ├── metadata/
│   │   ├── sample_metadata.csv        # Primary sample sheet — ALWAYS tracked in git
│   │   └── experimental_notes.md      # Free-text experimental context, protocol deviations, wet-lab notes
│   └── processed/                     # Intermediate processed outputs (gitignored for large files)
│       └── .gitkeep
│
├── scripts/
│   ├── 00_setup.R                     # Shared: library loading, path constants, color palettes, themes
│   ├── 01_qc/
│   │   └── 01_qc.qmd                 # Per-sample QC, filtering thresholds, doublet detection
│   ├── 02_preprocessing/
│   │   └── 02_preprocessing.qmd      # Normalization, HVG selection, scaling, PCA
│   ├── 03_integration/               # Present only if multi_batch = Y
│   │   └── 03_integration.qmd        # Batch correction: Harmony / RPCA / scVI / FastMNN
│   ├── 04_clustering/
│   │   └── 04_clustering.qmd         # Neighbor graph, UMAP, Louvain/Leiden, resolution sweep
│   ├── 05_annotation/
│   │   └── 05_annotation.qmd         # Marker genes, cell type assignment, confidence scoring
│   └── 06_downstream/                # Project-specific analyses
│       └── 06a_de_analysis.qmd       # Lettered suffixes for multiple parallel analyses
│
├── results/
│   ├── figures/                       # Individual plot outputs — organized by checkpoint
│   │   ├── 01_qc/                    # e.g., fig01_violin_qc_metrics.pdf
│   │   ├── 02_preprocessing/
│   │   ├── 03_integration/
│   │   ├── 04_clustering/
│   │   ├── 05_annotation/
│   │   └── 06_downstream/
│   ├── tables/                        # CSV/TSV output tables: DE results, cell counts, markers
│   └── objects/                       # Seurat/SCE RDS files — GITIGNORED
│       └── .gitkeep                   # Keeps the directory tracked in git despite empty
│
├── reports/                           # Rendered HTML/PDF outputs from qmd files
│   └── .gitkeep
│
└── docs/
    └── decisions/                     # Decision logs — one Markdown file per analytical checkpoint
        ├── 01_qc_decisions.md
        ├── 02_preprocessing_decisions.md
        ├── 03_integration_decisions.md
        ├── 04_clustering_decisions.md
        ├── 05_annotation_decisions.md
        └── 06_downstream_decisions.md
```

---

## Naming Conventions

### Scripts
- Two-digit prefix for phase: `01_`, `02_`, etc.
- Use snake_case for the descriptor: `01_qc.qmd`
- Multiple analytical branches within a phase: `04a_clustering_leiden.qmd`, `04b_clustering_rpca.qmd`
- Never overwrite iterative versions — Git manages version history. For experimental dead-ends, move scripts to an `archive/` subfolder within the phase directory rather than deleting them.

### R Objects (inside scripts)
- Seurat objects: `seu_{descriptor}` — e.g., `seu_raw`, `seu_filtered`, `seu_integrated`
- When saving to disk: `{project_name}_{phase}_{descriptor}_{YYYY-MM}.rds`
  - Example: `TGFb_EMT_01_seu_filtered_2024-11.rds`

### Figures
- `fig{nn}_{plot_type}_{descriptor}.pdf` + identical `.png` for quick preview
  - Example: `fig01_violin_qc_nFeature_pctmt.pdf`
  - Example: `fig04_umap_clusters_res0.5.pdf`
- Always save figures as both PDF (vector, for publication) and PNG (raster, for reports)

### Branches (Git)
- `main` — stable, checkpoint-committed code
- `wip/{descriptor}` — work in progress for exploratory analyses
- Merge to main only after the decision log for that phase is complete

---

## GCS Storage Structure

For objects that exceed practical local storage, use the following Google Cloud Storage path convention. Document all paths in `DATA_REGISTRY.md`.

```
gs://{bucket_name}/{project_name}/
├── raw/                  # Raw FASTQ files or count matrices from the sequencing facility
├── objects/              # Large Seurat / SingleCellExperiment RDS or H5AD objects
│   ├── 01_qc/
│   ├── 02_preprocessing/
│   └── ...
└── reports/              # Rendered HTML reports for sharing with collaborators
```

---

## DATA_REGISTRY.md Template

Every project's `data/raw/DATA_REGISTRY.md` should follow this structure:

```markdown
# Data Registry — {project_name}

## Raw Data

| Sample ID | Platform | Location | Format | Date Received | Notes |
|---|---|---|---|---|---|
| MDA_WT_Ctrl | 10X Flex | gs://bucket/project/raw/MDA_WT_Ctrl/ | filtered_feature_bc_matrix | 2024-11-01 | |

## Processed Objects

| Object | Checkpoint | Location | Date Created | Notes |
|---|---|---|---|---|
| seu_filtered | 01_qc | gs://bucket/project/objects/01_qc/TGFb_01_seu_filtered_2024-11.rds | 2024-11-10 | nFeat 200-6000, mt<15 |

## GCS Access

Bucket: gs://{bucket_name}
Access: `gcloud storage cp gs://... ./`
```
