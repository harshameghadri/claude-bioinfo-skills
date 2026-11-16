# Metadata Schema Reference

This file provides guidance on collecting experimental metadata for experiment types beyond the standard factorial scRNA-seq design. Read this file when the user's experiment does not fit the base schema in SKILL.md Phase 2.

The base schema (sample_id, cell_line, background, treatment, timepoint, platform, n_cells_expected, batch, notes) always applies. The sections below describe **additional columns** to append for each experiment type.

---

## 10X Flex (Fixed RNA Profiling)

Additional columns:

| Column | Description | Example |
|---|---|---|
| `probe_set` | Probe set version used | `v1.0`, `human_v1` |
| `multiplex_tag` | Cell Multiplexing Oligo (CMO) tag ID | `CMO301`, `CMO302` |
| `expected_cells_per_tag` | Cells loaded per CMO | `2000` |
| `fixed` | Fixed or fresh protocol | `fixed` |
| `fixation_date` | Date cells were fixed (relevant for batch effects) | `2024-11-01` |

Notes: 10X Flex multiplexes samples within one GEM well. The `multiplex_tag` column is essential for demultiplexing. Record `fixation_date` as this is a known source of batch variation.

---

## Parse Biosciences (Split-pipe)

Additional columns:

| Column | Description | Example |
|---|---|---|
| `sublibrary` | Parse sublibrary identifier | `SL001` |
| `well` | Source well on Parse plate | `A1` |
| `chemistry` | Parse chemistry version | `v2`, `v3` |
| `n_cells_loaded` | Cells loaded per well | `10000` |

Notes: Parse uses combinatorial barcoding. Record `sublibrary` carefully — it maps to the demultiplexing step in `split-pipe`. The `well` field is critical for troubleshooting ambient RNA and barcode collisions.

---

## CITE-seq (RNA + Protein Surface)

Additional base schema columns apply. Add:

| Column | Description | Example |
|---|---|---|
| `antibody_panel` | Name or version of ADT panel used | `TotalSeq-B v1` |
| `n_antibodies` | Number of antibody targets | `48` |
| `hashtag_oligo` | HTO barcode for sample demultiplexing | `HTO1`, `HTO2` |
| `adt_capture` | ADT library capture method | `CITE-seq-Count` |
| `protein_normalization` | Planned protein normalization | `CLR`, `DSB` |

Notes: Always store ADT and RNA counts separately at the raw level. Reference both paths in `DATA_REGISTRY.md`. DSB normalization requires background (empty droplet) libraries — document whether these were captured.

---

## Time-course Experiment

Additional columns:

| Column | Description | Example |
|---|---|---|
| `timepoint_hours` | Numeric timepoint in hours | `0`, `24`, `72`, `168` |
| `timepoint_label` | Human-readable label | `0h`, `24h`, `72h`, `Day7` |
| `passage_number` | Cell line passage at time of experiment | `P12` |
| `synchronization` | Cell cycle synchronization method if used | `serum_starvation`, `none` |

Notes: For time-course experiments, `timepoint_hours` (numeric) should always accompany `timepoint_label` (string) to enable correct ordering in downstream analysis without relying on factor level specification.

---

## Multi-tissue or Multi-organ

Additional columns:

| Column | Description | Example |
|---|---|---|
| `tissue` | Tissue of origin | `lung`, `liver`, `PBMC` |
| `tissue_region` | Sub-region if applicable | `alveolar`, `periportal` |
| `dissociation_protocol` | Dissociation method used | `collagenase_IV`, `trypsin` |
| `dissociation_time_min` | Dissociation duration | `30` |
| `cryopreserved` | Whether sample was cryopreserved | `yes`, `no` |

Notes: `dissociation_protocol` and `cryopreserved` are important covariates for batch correction. Record them even if integration is not currently planned — they are difficult to reconstruct retrospectively.

---

## Spatial Transcriptomics (Visium / Visium HD)

Additional columns:

| Column | Description | Example |
|---|---|---|
| `slide_id` | Capture area slide identifier | `V10J25-015_A1` |
| `capture_area` | Capture area on slide | `A1`, `B1` |
| `section_number` | Tissue section number | `3` |
| `tissue_thickness_um` | Section thickness | `10` |
| `permeabilization_time` | Permeabilization time in minutes | `12` |
| `stain` | Staining applied | `H&E`, `IF` |
| `image_path` | Path to the histology image | `data/raw/spatial/slide_A1_HE.tif` |

Notes: Permeabilization time is the single most impactful technical variable in Visium experiments and must be recorded. If using Visium HD, record the bin size used for analysis (2µm, 8µm, 16µm).

---

## Drug Resistance Experiments (Your TGFβ / Palbociclib design)

This schema fits your current experimental design well. Recommended additions to the base schema:

| Column | Description | Example |
|---|---|---|
| `resistance_induction_method` | How resistance was established | `chronic_exposure_6mo`, `genetic_CRISPR` |
| `resistance_passage` | Passage at which resistance was confirmed | `P8` |
| `drug_concentration_nM` | Concentration if relevant | `100`, `500` |
| `combination_order` | For combination treatments: which drug was given first | `TGFb_first`, `simultaneous` |
| `viability_pct` | Viability at harvest if measured | `85` |

Notes: The `combination_order` field is important for interpreting combination treatment effects, particularly when TGFβ and Palbociclib are used together — the sequence matters for EMT induction dynamics.

---

## General Guidance

**Completeness over perfection.** It is better to record a field as `unknown` or `not_measured` than to leave it blank — a blank field is ambiguous, whereas `unknown` is informative.

**Use controlled vocabulary where possible.** For categorical fields like `treatment` and `background`, define the allowed values at the start of the project in `experimental_notes.md` and adhere to them throughout. This prevents `TGFb` and `TGFβ` appearing as distinct groups in downstream analysis.

**Record the negative control explicitly.** Always include a `-ve` or `control` row for each cell line and background combination, even if it seems obvious. Downstream DE analysis depends on clean contrast definitions.
