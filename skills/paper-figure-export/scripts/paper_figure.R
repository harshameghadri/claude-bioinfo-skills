# paper_figure.R - publication-figure helpers for ggplot2 (and patchwork) in R.
#   source("scripts/paper_figure.R")
# Provides: pf_font(), OKABE_ITO, okabe(), theme_paper(), pf_save(), pf_row(), pf_stack(), pf_session(), pf_env_check(), JOURNAL_MM
# Design: physical size in millimetres, vector PDF with embedded fonts (cairo) plus PNG at a stated dpi, Okabe-Ito colours,
# a manifest of everything exported. Nothing here knows about any particular project or dataset.
suppressPackageStartupMessages(library(ggplot2))

# Widths in mm from the journals' own figure pages (see references/journal-sizes.md; confirm against the current guide of your target journal).
JOURNAL_MM <- list(
  nature = c(single = 89, onehalf = 120, double = 183),     # 1.5 column is 120 or 136 mm; maximum height ~170 mm with legend
  cell   = c(single = 85, onehalf = 114, double = 174))

# Okabe & Ito (2008) colour-universal palette, black first. Use okabe(n) for n <= 8 categories.
OKABE_ITO <- c(black = "#000000", orange = "#E69F00", skyblue = "#56B4E9", green = "#009E73",
               yellow = "#F0E442", blue = "#0072B2", vermillion = "#D55E00", purple = "#CC79A7")
okabe <- function(n, skip_black = FALSE, skip_yellow = FALSE) {
  p <- OKABE_ITO; if (skip_black) p <- p[names(p) != "black"]; if (skip_yellow) p <- p[names(p) != "yellow"]
  if (n > length(p)) stop("okabe(): at most ", length(p), " colours; use facets, shapes or direct labels beyond that", call. = FALSE)
  unname(p[seq_len(n)])
}

# First installed font family of `preferred`, else "sans". Helvetica/Arial are metric-compatible with Liberation Sans.
pf_font <- function(preferred = c("Arial", "Helvetica", "Liberation Sans", "Nimbus Sans", "DejaVu Sans")) {
  have <- tryCatch(unique(systemfonts::system_fonts()$family), error = function(e) character())
  hit <- preferred[preferred %in% have]
  if (length(hit)) hit[1] else { message("pf_font: none of ", paste(preferred, collapse = ", "), " installed; using generic 'sans'"); "sans" }
}

mm_to_in <- function(x) x / 25.4
PT_PER_MM <- 72.27 / 25.4     # ggplot2 geom_text size is in mm: size_mm = pt / PT_PER_MM  (e.g. 6 pt -> 6 / PT_PER_MM)
pt_to_geom <- function(pt) pt / PT_PER_MM

# Compact classic theme: base 8 pt, ticks/axis text 6 pt, legend 7 pt, thin lines (0.3 mm), bold 10 pt panel tags.
# Sizes sit inside Nature's 5-7 pt recommendation for text; change `axis_text`/`base_size` for other journals.
theme_paper <- function(base_size = 8, family = pf_font(), axis_text = 6, legend_text = 7, line_width = 0.3) {
  theme_classic(base_size = base_size, base_family = family) + theme(
    axis.title = element_text(size = base_size), axis.text = element_text(size = axis_text, colour = "black"),
    axis.line = element_line(linewidth = line_width), axis.ticks = element_line(linewidth = line_width),
    legend.text = element_text(size = legend_text), legend.title = element_text(size = legend_text), legend.key.size = unit(0.3, "cm"),
    legend.background = element_blank(), legend.key = element_blank(),
    strip.background = element_blank(), strip.text = element_text(size = base_size, hjust = 0),
    plot.title = element_text(size = base_size, face = "plain", hjust = 0), plot.title.position = "plot",
    plot.tag = element_text(size = 10, face = "bold"), plot.margin = margin(3, 8, 3, 8))
}

.pdf_device <- function() {
  if (isTRUE(capabilities("cairo"))) return(grDevices::cairo_pdf)
  warning("cairo is not available: falling back to pdf(); fonts will NOT be embedded", call. = FALSE)
  grDevices::pdf
}

# Export a ggplot/patchwork object.
#   width_mm / height_mm : final physical size (not inches). width_mm may be a JOURNAL_MM entry, e.g. JOURNAL_MM$nature[["single"]].
#   formats              : any of "pdf" (cairo, fonts embedded), "png" (dpi), "svg" (needs svglite), "tiff" (dpi, LZW)
#   note                 : caption text printed under the figure (wrapped to note_width characters); NULL = none
#   manifest             : TSV appended with name, format, file, size_mm, dpi, md5; NULL = no manifest
# Returns invisible(list(plot, files)). Files are named <outdir>/<name>.<format>.
pf_save <- function(p, name, width_mm, height_mm, outdir = "figures", formats = c("pdf", "png"), dpi = 300, note = NULL, note_width = 150,
                    manifest = file.path(outdir, "figure_manifest.tsv"), family = pf_font()) {
  stopifnot(is.numeric(width_mm), width_mm > 0, is.numeric(height_mm), height_mm > 0, is.character(name), nzchar(name), !grepl("[/\\\\ ]", name))
  bad <- setdiff(formats, c("pdf", "png", "svg", "tiff")); if (length(bad)) stop("unknown format(s): ", paste(bad, collapse = ", "), call. = FALSE)
  dir.create(outdir, recursive = TRUE, showWarnings = FALSE)
  if (!is.null(note)) {
    cap <- paste(strwrap(note, width = note_width), collapse = "\n")
    ct <- theme(plot.caption = element_text(size = 6, hjust = 0, family = family, colour = "grey30", lineheight = 1.05))
    p <- if (inherits(p, "patchwork")) p + patchwork::plot_annotation(caption = cap, theme = ct) else p + labs(caption = cap) + ct
  }
  w <- mm_to_in(width_mm); h <- mm_to_in(height_mm); files <- character()
  for (f in formats) {
    path <- file.path(outdir, paste0(name, ".", f)); files <- c(files, path)
    switch(f,
      pdf = ggsave(path, p, width = w, height = h, device = .pdf_device()),
      png = ggsave(path, p, width = w, height = h, dpi = dpi),
      tiff = ggsave(path, p, width = w, height = h, dpi = dpi, compression = "lzw"),
      svg = { if (!requireNamespace("svglite", quietly = TRUE)) stop("svg needs the svglite package", call. = FALSE); ggsave(path, p, width = w, height = h, device = svglite::svglite) })
  }
  if (!is.null(manifest)) {
    row <- data.frame(name = name, format = formats, file = basename(files), width_mm = width_mm, height_mm = height_mm,
                      dpi = ifelse(formats %in% c("png", "tiff"), dpi, NA), md5 = unname(tools::md5sum(files)), stringsAsFactors = FALSE)
    write.table(row, manifest, sep = "\t", quote = FALSE, row.names = FALSE, col.names = !file.exists(manifest), append = file.exists(manifest))
  }
  invisible(list(plot = p, files = files))
}

# Compose panels with patchwork. Each row is built independently so that the axis alignment of one row never constrains the
# next; panel tags (A, B, ...) continue across rows when `tags` is given per row.
pf_row <- function(plots, tags = NULL, widths = NULL) {
  if (!requireNamespace("patchwork", quietly = TRUE)) stop("pf_row needs the patchwork package", call. = FALSE)
  r <- patchwork::wrap_plots(plots, nrow = 1, widths = widths)
  if (!is.null(tags)) r <- r + patchwork::plot_annotation(tag_levels = list(tags), theme = theme(plot.tag = element_text(size = 10, face = "bold")))
  patchwork::wrap_elements(full = r)
}
pf_stack <- function(rows, heights = NULL) {
  if (!requireNamespace("patchwork", quietly = TRUE)) stop("pf_stack needs the patchwork package", call. = FALSE)
  patchwork::wrap_plots(rows, ncol = 1, heights = heights)
}

pf_session <- function(path = "sessionInfo.txt") { dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE); writeLines(capture.output(sessionInfo()), path); invisible(path) }

# Report what the environment can and cannot do before a long figure script runs.
pf_env_check <- function() {
  d <- data.frame(item = c("cairo", "font", "patchwork", "svglite", "ragg"),
                  value = c(as.character(isTRUE(capabilities("cairo"))), pf_font(), as.character(requireNamespace("patchwork", quietly = TRUE)),
                            as.character(requireNamespace("svglite", quietly = TRUE)), as.character(requireNamespace("ragg", quietly = TRUE))))
  print(d, row.names = FALSE); invisible(d)
}
