# Journal figure presets (starting points, not rules)

Widths below come from the journals' own pages or from publisher guides that quote them (looked up 2026-11-17). Journals revise
their guides: confirm against the current author instructions of the target journal before final export, and use the audit tool
(`scripts/figure_audit.py`) to check what you exported.

| Journal family | Single column | 1.5 column | Double column | Other stated limits |
|---|---|---|---|---|
| Nature (research) | 89 mm | 120 or 136 mm | 183 mm | Maximum figure height about 170 mm (leaves room for the legend); text 5-7 pt, sans-serif (Helvetica/Arial); vector artwork preferred for graphs; raster at least 300 dpi at final size |
| Cell Press (e.g. Cell) | 85 mm | 114 mm | 174 mm | Text 6-8 pt (Arial); colour/greyscale 300 dpi, black-and-white 500 dpi, line art 1000 dpi; TIFF or PDF preferred; RGB |

Some Cell Press titles use other layouts (3-column and other formats exist); some Nature Portfolio titles differ in width (for example 86/178 mm
or 88/180 mm). Check the journal you target.

`JOURNAL_MM` in `scripts/paper_figure.R` holds the Nature and Cell widths above; add your own entries for other journals.

## Reading the numbers

- Final size is physical: export at the printed width, not at a large size to be shrunk later. Shrinking a 183 mm figure to 89 mm shrinks 6 pt text to about 3 pt.
- Pixels = mm / 25.4 x dpi. For 89 mm at 300 dpi that is 1051 px; the audit tool checks the recorded dpi and the pixel width.
- A PDF has no dpi. Check page size (mm) and font embedding instead.
