---
name: bioinfo-project-manager
description: >
  Manages bioinformatics project initialization, folder scaffolding, experimental metadata 
  collection, git setup, renv reproducibility, analytical decision logging, and Notion 
  journal creation for single-cell RNA-seq and multi-omics projects. Always trigger this 
  skill when the user wants to start a new bioinformatics project, set up or reorganize a 
  project structure, collect experimental metadata, scaffold analysis scripts, create 
  decision logs at analytical checkpoints, document methodological choices, or set up a 
  Notion project journal. Also trigger on: "new project", "set up project", "start 
  analysis", "initialize repo", "scaffold my project", "log my decisions", "QC done 
  what next", "document this step", or any request to organize single-cell work. Covers 
  10X Flex, Parse, CITE-seq, Smart-seq, and multi-platform projects. Always use this 
  skill — even if the user only asks about one part of the workflow — because the steps 
  are interdependent and skipping scaffolding causes downstream pain.
---

# Bioinformatics Project Manager

A structured workflow for initializing, scaffolding, and documenting single-cell and 
multi-omics projects on Mac (local compute) with Google Cloud warm storage — from first 
git commit to final figure.

## Default Environment (edit to match your setup)
- **Compute:** Mac M1 Max local; heavy object storage on Google Cloud Storage (warm tier)
- **IDE:** RStudio; primary language R with `renv` for environment locking
- **Platforms:** 10X Flex, Parse (expandable per project)
- **Documentation:** `.qmd` files for analysis; Notion for the project journal
- **Git policy:** Personal repo; committed incrementally; pushed publicly on manuscript submission
- **Large file policy:** `.rds`, `.h5seurat`, `.h5ad` are NEVER committed to git — always gitignored and referenced in `DATA_REGISTRY.md`

---

## PHASE 1 — Project Initialization

### 1.1 New vs. Existing Project

Ask the user:
> "Are you initializing a **new** project or picking up an **existing** one?"

**If new:** proceed through all phases in order.  
**If existing:** jump to Phase 5 (Checkpoint Protocol). Offer to retroactively generate missing docs.

### 1.2 Gather Core Project Details

Collect the following before creating anything on disk:

| Field | Prompt |
|---|---|
| `project_name` | Short identifier — snake_case or PascalCase, no spaces. This becomes the folder and repo name. |
| `hypothesis` | One-to-three sentence biological hypothesis or main research question. |
| `platform` | Primary platform(s): 10X Flex / Parse / CITE-seq / other |
| `multi_batch` | Is this a multi-sample or multi-batch project requiring integration? (Y/N) |
| `gcs_bucket` | GCS bucket name for heavy object storage, if known (can be filled later) |

### 1.3 Confirm Before Creating

Print a confirmation block and wait for explicit user approval before running any bash:

```
Project name:    {project_name}
Root path:       ~/Projects/{project_name}/
Git init:        Yes
renv init:       Yes (will prompt to run in RStudio)
Notion journal:  Yes
Proceed?         (Y/N)
```

---

## PHASE 2 — Experimental Metadata Collection

### 2.1 Accept or Collect Sample Metadata

> "Do you have a sample sheet (CSV/spreadsheet/image), or should I prompt you interactively?"

**If the user provides a file or image:** extract the data, infer columns, and map to the standard schema below. Confirm your interpretation before writing anything.

**If interactive:** prompt for each field. Adapt — not all fields apply to every experiment. Follow the user's naming conventions exactly (e.g. `LineA_WT_Ctrl` style from their existing sheets).

**Standard schema** (modelled on a factorial scRNA-seq experiment):

| Column | Type | Example |
|---|---|---|
| `sample_id` | string, unique | `LineA_WT_Ctrl` |
| `cell_line` | string | `CellLineA` |
| `background` | categorical | `WT`, `DrugB-Resistant` |
| `treatment` | categorical/string | `DrugA (72h)`, `-ve` |
| `timepoint` | string (if not embedded in treatment) | `72h` |
| `platform` | string | `10X Flex`, `Parse` |
| `n_cells_expected` | integer | `5000` |
| `batch` | string | `batch_1` |
| `notes` | free text | any caveats |

See `references/metadata-schema.md` for platform-specific field additions (CITE-seq, time-course, multi-tissue, spatial).

### 2.2 Write Metadata Files

- Write `data/metadata/sample_metadata.csv` from collected fields
- Capture the hypothesis and key metadata into `manifest.yml`

---

## PHASE 3 — Infrastructure Setup

### 3.1 Scaffold Folder Structure

Run the bash block below after user confirmation. For annotated descriptions of every directory, read `references/folder-structure.md`.

```bash
PROJECT_NAME="{project_name}"
BASE="$HOME/Projects/$PROJECT_NAME"

mkdir -p "$BASE"/{data/{raw,metadata,processed},\
results/{figures/{01_qc,02_preprocessing,03_integration,04_clustering,05_annotation,06_downstream},\
tables,objects},reports,docs/decisions}

mkdir -p "$BASE"/scripts/{01_qc,02_preprocessing,03_integration,\
04_clustering,05_annotation,06_downstream}

touch "$BASE"/data/processed/.gitkeep
touch "$BASE"/results/objects/.gitkeep
touch "$BASE"/reports/.gitkeep
touch "$BASE"/data/raw/DATA_REGISTRY.md
touch "$BASE"/scripts/00_setup.R
touch "$BASE"/manifest.yml
touch "$BASE"/README.md
```

**Conditional additions:**
- If `multi_batch = N`: remove `03_integration/` directories
- If CITE-seq: add `data/raw/protein/` and `scripts/02b_adt_processing/`
- If Visium/spatial: add `data/raw/spatial/` and `scripts/02c_spatial/`

### 3.2 Write .gitignore

Read `references/templates.md` → **Section: .gitignore** and write it verbatim to `{project_name}/.gitignore`.

Critical exclusions to enforce:
- Large R objects: `*.rds`, `*.RData`, `*.h5seurat`, `*.h5ad`, `*.loom`
- Processed data dirs: `data/processed/`, `results/objects/`
- renv library: `renv/library/`, `.Rproj.user/`
- Credentials: `.env`, `*_token*`, `*_key.txt`, `secrets/`
- Raw data: `data/raw/` (document paths in DATA_REGISTRY.md instead)

### 3.3 Initialize Git

```bash
cd "$HOME/Projects/$PROJECT_NAME"
git init
git add .gitignore README.md manifest.yml \
        data/metadata/sample_metadata.csv \
        data/raw/DATA_REGISTRY.md
git commit -m "chore: initialize project scaffold — {project_name}"
```

### 3.4 Initialize renv

Instruct the user to run the following in RStudio after opening the `.Rproj` file:
```r
install.packages("renv")
renv::init()
```
Then commit:
```bash
git add renv.lock .Rprofile
git commit -m "chore: initialize renv environment"
```

### 3.5 Populate README.md and manifest.yml

Read `references/templates.md` → **Section: README** and **Section: manifest.yml**. Populate both from the metadata and hypothesis collected in Phase 2. The README should include: project title, hypothesis, sample overview table, platform, reproducibility instructions, and data access notes.

### 3.6 Scaffold 00_setup.R

Read `references/templates.md` → **Section: 00_setup.R**. Write a project-specific setup script using the detected platform, sample list, and any palette or path conventions needed for this project.

---

## PHASE 4 — Notion Journal Setup

*Requires the Notion MCP connector. Confirm it is active before proceeding.*

### 4.1 Find or Create the Project Database

Use `notion-search` to look for an existing page or database named "Bioinformatics Projects".

- **Found:** create a new child page for this project within it.
- **Not found:** create a new top-level page titled "🧬 Bioinformatics Projects" and add this project as the first entry.

### 4.2 Structure the Project Page

Create a Notion page via `notion-create-pages` with these sections:
- **Title:** `{project_name}` with a `Status` property set to `Active`
- **Hypothesis:** plain text block from Phase 2
- **Sample Table:** reproduced from `sample_metadata.csv`
- **Analysis Log:** an empty inline database with columns: `Date | Checkpoint | Decision Summary | Open Flags`
- **Links:** local project path; GCS bucket URI (if known)

### 4.3 Record the Notion URL

Write the Notion page URL into `manifest.yml` under the key `notion_journal`. Commit:
```bash
git add manifest.yml
git commit -m "docs: link Notion journal to project manifest"
```

---

## PHASE 5 — Analytical Checkpoint Protocol

Trigger this phase whenever the user starts a new analysis phase, finishes a major step, or makes a key methodological decision.

### 5.1 Identify the Current Checkpoint

| # | Checkpoint | Script | Key Decision Points |
|---|---|---|---|
| 01 | QC & Filtering | `01_qc/01_qc.qmd` | nFeature thresholds, percent.mt cutoff, doublet method, cells retained per sample |
| 02 | Preprocessing | `02_preprocessing/02_preprocessing.qmd` | Normalization (SCTransform vs logNormalize), n HVGs, PCA dims used |
| 03 | Integration | `03_integration/03_integration.qmd` | Method (Harmony / RPCA / scVI / FastMNN), batch variables, evaluation metric |
| 04 | Clustering | `04_clustering/04_clustering.qmd` | Resolution, algorithm (Louvain / Leiden), cluster stability check |
| 05 | Annotation | `05_annotation/05_annotation.qmd` | Marker sources, manual vs automated (SingleR / scType), confidence level |
| 06+ | Downstream | `06_downstream/*.qmd` | DE method, trajectory algorithm, pathway database, statistical thresholds |

### 5.2 Scaffold the Checkpoint Script

If the `.qmd` file for this checkpoint does not yet exist, create it from the header template in `references/templates.md` → **Section: qmd header**. The header captures: checkpoint name, date, author, and a `source("../00_setup.R")` call at the top.

### 5.3 Prompt the Decision Log

Ask the user these five questions — do not skip any, even if the user is in a hurry:

1. **Decision made:** What threshold, method, or parameter did you choose?
2. **Rationale:** What data or biological reasoning supports this decision?
3. **Alternatives rejected:** What did you try or consider that you discarded, and why?
4. **Outputs produced:** File paths of saved objects and figures from this step.
5. **Open flags:** Any uncertainty, caveats, or questions to revisit in a later step?

Write answers to `docs/decisions/{checkpoint}_decisions.md` using the format in `references/templates.md` → **Section: Decision Log**.

### 5.4 Append to Notion Analysis Log

Use `notion-update-page` or `notion-create-comment` to append a timestamped row to the Analysis Log table on the project page. Include: date, checkpoint name, one-line decision summary, open flags.

### 5.5 Commit the Checkpoint

```bash
git add scripts/{checkpoint}/ \
        docs/decisions/{checkpoint}_decisions.md \
        results/figures/{checkpoint}/
git commit -m "analysis({checkpoint}): {one-line summary of key decision}"
```

---

## Core Principles — Enforce These Always

1. **No large binaries in git.** `.rds`, `.h5seurat`, `.h5ad` are always gitignored. Locations are documented in `DATA_REGISTRY.md` and `manifest.yml`. Remind the user if they attempt to stage large files.
2. **One script per analytical phase.** Numbered `01_`, `02_`, etc. Multiple branches within a phase use letter suffixes: `04a_`, `04b_`.
3. **No checkpoint commit without a decision log.** The log for that phase must be written before `git commit` runs.
4. **renv is snapshotted after every package install.** Run `renv::snapshot()` and commit `renv.lock` immediately after.
5. **The Notion journal is the narrative; git is the technical record.** Both must stay current.
6. **DATA_REGISTRY.md is the source of truth for data paths.** Update it every time a new object is saved to GCS or outside the repo.

---

## Reference Files

Load only the file relevant to the current task — do not pre-load all of them:

| File | When to read it |
|---|---|
| `references/folder-structure.md` | Scaffolding directories or explaining the project layout |
| `references/templates.md` | Writing any file: `.gitignore`, README, `manifest.yml`, `00_setup.R`, decision log, qmd header |
| `references/metadata-schema.md` | Collecting metadata for non-standard experiment types (CITE-seq, time-course, multi-tissue, spatial) |
