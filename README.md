# claude-bioinfo-skills

Skills for bioinformatics: single-cell RNA-seq (Seurat, scverse), spatial transcriptomics (Visium HD, Xenium), public data download, host-pathogen references, QC, publication figures, cell-type annotation, R package development, Quarto reporting and reproducible project scaffolding. Drop-in `SKILL.md` folders for Claude Science, Claude Code and Claude.ai; the newer skills ship tested scripts and are written to work with any model or agent harness (see [docs/SKILL_STANDARD.md](docs/SKILL_STANDARD.md)).

## Skills

| Skill | Use it for | Language |
|---|---|---|
| [`stepwise-cluster-labelling`](skills/stepwise-cluster-labelling) | Classical, manual cell-type labelling of scRNA/snRNA/imaging-panel data (Xenium, CosMx, MERFISH): per-sample RPCA integration, multiplet/low-quality cluster naming, lineage subsetting and purification rounds | R / Seurat |
| [`spatial-seurat-qc`](skills/spatial-seurat-qc) | Visium HD loading, QC, SCTransform, spatially variable features, clustering | R / Seurat |
| [`quarto-r-report`](skills/quarto-r-report) | Reproducible, self-contained Quarto HTML reports for single-cell and spatial analyses | R / Quarto |
| [`r-pkg-dev`](skills/r-pkg-dev) | R package workflow: usethis/devtools setup, Roxygen2, renv, function templates | R |
| [`bioinfo-project-manager`](skills/bioinfo-project-manager) | Project scaffolding, metadata collection, git + renv setup, analytical decision logging | R, git |
| [`sra-ena-geo-download`](skills/sra-ena-geo-download) | Reliable download of public sequencing data (ENA, SRA, GEO supplementary): accession resolution, checksum-verified resumable fetching with a fallback ladder, safe queueing | Python (stdlib), aria2c |
| [`host-pathogen-composite-reference`](skills/host-pathogen-composite-reference) | Host + virus/bacteria reference for STAR/STARsolo: collision-checked merge, per-gene GTF so CDS-only genes are counted, index parameters, barcode-whitelist pre-flight | Python (stdlib), STAR |
| [`parse-vs-10x-qc`](skills/parse-vs-10x-qc) | Cell QC for Parse Evercode and 10x matrices: orientation-safe readers, MAD floors, beta-binomial mitochondrial test, MALAT1-aware top-gene rule, well-contamination screen, thinning, optional doublets | R |
| [`paper-figure-export`](skills/paper-figure-export) | Publication figures from ggplot2: size in mm, embedded fonts, Okabe-Ito palette, export manifest, plus a file auditor and a colour-blind palette checker | R, Python (stdlib) |
| [`dataset-audit`](skills/dataset-audit) | Pre-analysis audit: file completeness and checksums, FASTQ pairing, count-matrix integrity, sample sheets, replicate and confounding checks | Python (stdlib) |

## Install

**Claude Code (plugin marketplace)**
```
/plugin marketplace add harshameghadri/claude-bioinfo-skills
/plugin install bioinfo-skills@claude-bioinfo-skills
```

**Claude Code (manual)**: copy any folder from `skills/` into `~/.claude/skills/` (or a project's `.claude/skills/`).

**Claude.ai / Claude Science**: zip a skill folder and upload it in your Skills settings.

## Conventions

- One folder per skill under `skills/`; the folder name equals the `name:` in `SKILL.md`.
- `description:` is what triggers the skill, so it lists the trigger phrases.
- Long material lives in `references/` and is loaded only when needed; helper code lives in `scripts/` or alongside `SKILL.md`.
- Skills with `scripts/` have standalone, `--help`-documented programs and an offline `tests/run.sh`; no model, network or real data is needed to run the tests.
- `python3 scripts/validate_skills.py` checks frontmatter, referenced files, script syntax and `--help`, vendor-specific wording and publishing hygiene; `scripts/run_tests.sh` runs every skill's tests. CI runs both on every PR. The rules are in [docs/SKILL_STANDARD.md](docs/SKILL_STANDARD.md).

## Status

Skills encode one analyst's defaults (Seurat-centric R workflows, renv, Quarto); check the "Default environment" sections and adapt them to your setup. Network endpoints (ENA, NCBI) are exercised in CI only against recorded responses and a local server; the live services are not called by the tests. The scDblFinder path of `parse-vs-10x-qc` is optional and not covered by the offline tests.

## License

Apache-2.0, see [LICENSE](LICENSE).
