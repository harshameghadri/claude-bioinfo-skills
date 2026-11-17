---
name: paper-figure-export
description: Export publication-ready figures from R (ggplot2/patchwork) at a stated physical size with embedded fonts, a colour-blind-safe Okabe-Ito palette, 300+ dpi PNG, a caption note and an export manifest, then audit the files (size in mm, dpi, embedded fonts) and check a palette for colour-vision deficiencies. Use for journal figures, Nature/Cell column widths, 'make this figure paper-ready', font embedding, figure dpi, panel composition, colour-blind-safe colours.
---

# Paper-ready figure export (R)

Most figure rework comes from three avoidable things: exporting at an arbitrary size and shrinking later, fonts that are not embedded or not the journal's, and palettes that fail for colour-blind readers. This skill fixes the size in millimetres up front, exports vector PDF (fonts embedded) plus PNG at a stated dpi, records what was exported, and provides two independent checkers (Python, standard library only) so the result is verified from the files themselves.

Requirements: R with `ggplot2` and `systemfonts` (optional: `patchwork` for composition, `svglite` for SVG); `python3` for the checkers; `pdffonts`/`pdfinfo` (poppler) improve the PDF checks and are used when installed. Paths are relative to this skill folder.

## Procedure

1. **Fix the target before plotting.** Pick the journal and column (`JOURNAL_MM$nature[["single"]]` is 89 mm; see `references/journal-sizes.md`), the maximum height and the dpi. Write them down; they go into the export call and the audit call.
2. **Build the plot with the helper theme and palette.**
   ```r
   source("scripts/paper_figure.R")
   p <- ggplot(d, aes(x, y, colour = group)) + geom_point() +
        scale_colour_manual(values = okabe(3, skip_black = TRUE)) + theme_paper()
   ```
   `theme_paper()` uses an 8 pt base, 6 pt axis text, 7 pt legends, 0.3 mm lines and 10 pt bold panel tags. `pf_font()` picks Arial, Helvetica or the metric-compatible Liberation Sans, whichever is installed, and says so when it falls back to generic sans. Use one colour per entity across all figures of a paper. `okabe(n)` stops at 8 colours: beyond that use facets, shapes or direct labels.
3. **Compose panels (optional).** `pf_row(list(a, b), tags = c("A","B"))` and `pf_stack(list(row1, row2), heights = c(1, 1))` build each row independently, so alignment in one row cannot distort the next; tags continue across rows.
4. **Export.**
   `pf_save(p, "fig1", width_mm = 89, height_mm = 70, outdir = "figures", formats = c("pdf","png"), dpi = 300, note = "n = ... per group; error bars show ...")`
   PDF uses the cairo device (fonts embedded; without cairo it warns and falls back). `note` becomes a wrapped caption line under the figure for sample sizes, replicate definition and statistics. `figure_manifest.tsv` in `outdir` records name, format, file, size, dpi and md5 of every file. Run `pf_session("figures/sessionInfo.txt")` to keep the package versions.
5. **Audit the files, not the intention.**
   `python3 scripts/figure_audit.py figures/fig1.png figures/fig1.pdf --expect-width-mm 89 --max-height-mm 170 --expect-dpi 300`
   Exit 4 and a FAIL line mean size, dpi or font embedding is wrong. SKIP means a check could not run (for example no `pdffonts`); it is not a pass.
6. **Check the palette** when you use colours other than `okabe()`:
   `python3 scripts/palette_check.py --colors "#E69F00,#56B4E9,#009E73" --min-delta 15`
   It simulates protan, deutan and tritan vision and reports the closest pair. Exit 4 means two colours become too similar. This is a screening heuristic; also look at the figure with a colour-blindness simulator or in greyscale, and do not rely on colour alone for thin lines or small points (add shape or direct labels).
7. **Look at the figure at final size** (print the PNG at 100% or open the PDF at the physical width). Text smaller than the journal minimum, overlapping labels and clipped axis titles are only visible this way.

## Rules that prevent known failures

- Size is set in millimetres at export (`width_mm`); never rescale an exported file to fit.
- Use vector PDF for plots and the PNG only for previews or raster-only content; photographs and heatmaps with very many cells may need a raster layer at the final dpi.
- Text sizes: stay inside the journal's range (Nature asks for 5-7 pt). `geom_text`/`annotate` sizes are in mm: use `pt_to_geom(6)`.
- State n and what a replicate is in the figure note or legend; error bars must say what they are.
- Do not embed project verdicts or project-specific labels in shared helpers: keep those in the analysis script that calls `pf_save`.
- Fonts: install Arial/Helvetica or Liberation Sans; a missing font silently becomes a different family in the export. `pf_env_check()` prints what is used.

## Outputs

`<outdir>/<name>.pdf|png|svg|tiff`, `figure_manifest.tsv`, optionally `sessionInfo.txt`; audit and palette reports on stdout.

## Testing

`bash tests/run.sh` (27 tests): generated figures are audited for exact pixel width, recorded dpi, page size in mm and embedded fonts; a plain `pdf()` export with unembedded fonts must be caught; wrong sizes, wrong dpi, missing dpi metadata, corrupt files and bad arguments must fail with the documented exit codes; the palette checker must pass Okabe-Ito and fail a red/green pair under deuteranopia. R-dependent tests are skipped when R is absent.
