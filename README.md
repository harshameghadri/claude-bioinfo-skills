# claude-bioinfo-skills

Claude skills for bioinformatics: single-cell RNA-seq (Seurat, scverse), spatial transcriptomics (Visium HD, Xenium), cell-type annotation, R package development, Quarto reporting and reproducible project scaffolding. Drop-in SKILL.md folders for Claude Science, Claude Code and Claude.ai.

## Skills

| Skill | Use it for | Language |
|---|---|---|
| [`stepwise-cluster-labelling`](skills/stepwise-cluster-labelling) | Classical, manual cell-type labelling of scRNA/snRNA/imaging-panel data (Xenium, CosMx, MERFISH): per-sample RPCA integration, multiplet/low-quality cluster naming, lineage subsetting and purification rounds | R / Seurat |
| [`spatial-seurat-qc`](skills/spatial-seurat-qc) | Visium HD loading, QC, SCTransform, spatially variable features, clustering | R / Seurat |
| [`quarto-r-report`](skills/quarto-r-report) | Reproducible, self-contained Quarto HTML reports for single-cell and spatial analyses | R / Quarto |
| [`r-pkg-dev`](skills/r-pkg-dev) | R package workflow: usethis/devtools setup, Roxygen2, renv, function templates | R |
| [`bioinfo-project-manager`](skills/bioinfo-project-manager) | Project scaffolding, metadata collection, git + renv setup, analytical decision logging | R, git |

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
- `python3 scripts/validate_skills.py` checks the frontmatter (CI runs it on every PR).

## Status

Early release (v0.1.0). Skills encode one analyst's defaults (Seurat-centric R workflows, renv, Quarto); check the "Default environment" sections and adapt them to your setup.

## License

Apache-2.0, see [LICENSE](LICENSE).
