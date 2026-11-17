#!/usr/bin/env Rscript
# run_qc.R - single-cell QC for Parse Evercode and/or 10x Genomics count matrices. See SKILL.md.
# Writes plain TSV tables (cell_qc.tsv, thresholds.tsv, sample_summary.tsv, [well_spikes*.tsv]) to --outdir.
# Exit codes: 0 ok, 1 error, 2 usage error.

args <- commandArgs(trailingOnly = TRUE)
script_dir <- local({
  a <- grep("^--file=", commandArgs(FALSE), value = TRUE)
  if (length(a)) dirname(normalizePath(sub("^--file=", "", a[1]))) else "."
})

usage <- function() cat(
"Usage: Rscript run_qc.R (--parse NAME=DIR[@POOL] | --10x NAME=DIR[@POOL])... --outdir DIR [options]

Inputs (repeatable, may be mixed):
  --parse NAME=DIR[@POOL]   Parse split-pipe DGE directory (count_matrix.mtx[.gz], all_genes.csv[.gz], cell_metadata.csv[.gz])
  --10x   NAME=DIR[@POOL]   10x matrix directory (matrix.mtx[.gz], barcodes.tsv[.gz], features.tsv[.gz])
  POOL is an optional label: thresholds are fitted per POOL (default: one pool for all samples).

Options:
  --outdir DIR         output directory (created)                                       [required]
  --species human|mouse  gene-name conventions for mitochondrial genes / MALAT1        [human]
  --mad-k K            depth and gene floors at median - K*MAD of log10 values         [4]
  --mt-alpha P         flag mt protein-coding excess when beta-binomial upper tail <= P [0.001]
  --top-frac F         flag cells whose top gene exceeds this UMI fraction              [0.20]
  --sensitivity        also write per-sample 3-MAD flags (v1_*; not applied to qc_pass)
  --no-spike-screen    skip the Parse round-1 well screen
  --spike-fc N         well screen: minimum fold change                                 [5]
  --spike-log10p X     well screen: log10 p threshold                                   [-20]
  --thin-target N|auto|none   write thinned_counts.rds (binomial thinning to N UMIs; auto = 10th percentile of passing cells) [none]
  --save-rds           write qc_counts.rds (combined genes x cells matrix + tables)
  --help               this text
", file = stdout())

fail <- function(msg, code = 1L) { cat("run_qc.R: ", msg, "\n", sep = "", file = stderr()); quit(status = code, save = "no") }

if (!length(args) || any(args %in% c("-h", "--help"))) { usage(); quit(status = if (length(args)) 0L else 2L, save = "no") }

opt <- list(species = "human", mad_k = 4, mt_alpha = 0.001, top_frac = 0.20, sensitivity = FALSE, spike = TRUE,
            spike_fc = 5, spike_log10p = -20, thin = "none", save_rds = FALSE, outdir = NULL, inputs = list())
i <- 1L
nxt <- function() { if (i + 1L > length(args)) fail(paste("missing value after", args[i]), 2L); i <<- i + 1L; args[i] }
while (i <= length(args)) {
  a <- args[i]
  switch(a,
    "--parse" = , "--10x" = { v <- nxt(); opt$inputs[[length(opt$inputs) + 1L]] <- list(platform = sub("^--", "", a), spec = v) },
    "--outdir" = opt$outdir <- nxt(),
    "--species" = opt$species <- nxt(),
    "--mad-k" = opt$mad_k <- as.numeric(nxt()),
    "--mt-alpha" = opt$mt_alpha <- as.numeric(nxt()),
    "--top-frac" = opt$top_frac <- as.numeric(nxt()),
    "--sensitivity" = opt$sensitivity <- TRUE,
    "--no-spike-screen" = opt$spike <- FALSE,
    "--spike-fc" = opt$spike_fc <- as.numeric(nxt()),
    "--spike-log10p" = opt$spike_log10p <- as.numeric(nxt()),
    "--thin-target" = opt$thin <- nxt(),
    "--save-rds" = opt$save_rds <- TRUE,
    fail(paste("unknown argument:", a), 2L))
  i <- i + 1L
}
if (is.null(opt$outdir)) fail("--outdir is required", 2L)
if (!length(opt$inputs)) fail("give at least one --parse or --10x input", 2L)
if (!opt$species %in% c("human", "mouse")) fail("--species must be human or mouse", 2L)
if (anyNA(c(opt$mad_k, opt$mt_alpha, opt$top_frac, opt$spike_fc, opt$spike_log10p))) fail("a numeric option could not be parsed", 2L)
if (!opt$thin %in% c("none", "auto") && is.na(suppressWarnings(as.numeric(opt$thin)))) fail("--thin-target must be a number, auto or none", 2L)

res <- tryCatch({
  suppressPackageStartupMessages({ library(Matrix); library(data.table) })
  source(file.path(script_dir, "read_matrices.R")); source(file.path(script_dir, "qc_core.R"))
  dir.create(opt$outdir, showWarnings = FALSE, recursive = TRUE)

  parse_spec <- function(s) {
    pool <- "all"
    if (grepl("@", s, fixed = TRUE)) { pool <- sub(".*@", "", s); s <- sub("@[^@]*$", "", s) }
    if (!grepl("=", s, fixed = TRUE)) stop("input must look like NAME=DIR[@POOL]: ", s, call. = FALSE)
    list(name = sub("=.*", "", s), dir = sub("^[^=]*=", "", s), pool = pool)
  }
  loaded <- lapply(opt$inputs, function(x) {
    sp <- parse_spec(x$spec)
    message("reading ", x$platform, " sample ", sp$name, " from ", sp$dir)
    r <- if (x$platform == "parse") read_parse(sp$dir, sp$name) else read_10x(sp$dir, sp$name)
    r$meta[, pool := sp$pool]; r
  })
  nm <- vapply(opt$inputs, function(x) parse_spec(x$spec)$name, "")
  if (anyDuplicated(nm)) stop("duplicate sample names: ", paste(nm[duplicated(nm)], collapse = ", "), call. = FALSE)

  # samples from different platforms may have different gene tables: intersect on gene_id
  common <- Reduce(intersect, lapply(loaded, function(x) x$genes$gene_id))
  if (!length(common)) stop("samples share no gene_id; were they quantified against the same annotation?", call. = FALSE)
  if (any(vapply(loaded, function(x) nrow(x$genes), 1L) != length(common)))
    message("note: restricting to ", length(common), " gene_ids shared by all samples")
  loaded <- lapply(loaded, function(x) { k <- match(common, x$genes$gene_id); list(counts = x$counts[k, , drop = FALSE], genes = x$genes[k], meta = x$meta) })
  D <- combine_samples(loaded)
  stopifnot(identical(colnames(D$counts), D$meta$cell_id))

  frac <- list(RN7SK = c("RN7SK", "Rn7sk"), RMRP = c("RMRP", "Rmrp"), RPPH1 = c("RPPH1", "Rpph1"),
               histone = grep(if (opt$species == "human") "^H(1-[0-9]+|2AC[0-9]+|2BC[0-9]+|3C[0-9]+|4C[0-9]+)$" else "^Hist[0-9]",
                              D$genes$gene_name, value = TRUE))
  met <- cell_metrics(D$counts, D$genes, species = opt$species, fraction_genes = frac)
  stopifnot(identical(met$cell_id, D$meta$cell_id))

  parts <- split(seq_len(nrow(met)), D$meta$pool); out <- list(); thr <- list()
  for (p in names(parts)) {
    ix <- parts[[p]]
    f <- qc_flags(met[ix], k = opt$mad_k, mt_alpha = opt$mt_alpha, top_frac = opt$top_frac,
                  sample = if (opt$sensitivity) D$meta$sample[ix] else NULL)
    t <- attr(f, "thresholds"); t[, pool := p]; thr[[p]] <- t
    out[[p]] <- f
    message(sprintf("pool %s: %d cells, %d pass (%.1f%%)", p, nrow(f), sum(f$qc_pass), 100 * mean(f$qc_pass)))
  }
  cells <- rbindlist(out); cells <- cells[match(met$cell_id, cell_id)]
  cells <- cbind(D$meta[, .(sample, platform, pool)], cells)
  extra <- intersect(c("well", "sublib", "barcode"), names(D$meta))
  for (e in extra) cells[[e]] <- D$meta[[e]]
  setcolorder(cells, c("cell_id", setdiff(names(cells), "cell_id")))
  fwrite(cells, file.path(opt$outdir, "cell_qc.tsv"), sep = "\t", na = "NA")
  fwrite(rbindlist(thr), file.path(opt$outdir, "thresholds.tsv"), sep = "\t")

  summ <- cells[, .(n_cells = .N, n_pass = sum(qc_pass), pct_pass = round(100 * mean(qc_pass), 2),
                    fail_depth = sum(qc_depth), fail_genes = sum(qc_genes), fail_mt = sum(qc_mt), fail_top = sum(qc_top),
                    median_umi = median(n_umi), median_genes = median(n_genes),
                    median_frac_mtpc = signif(median(frac_mtpc, na.rm = TRUE), 3),
                    median_frac_mtrrna_raw = signif(median(frac_mtrrna, na.rm = TRUE), 3)), by = .(sample, platform, pool)]
  fwrite(summ, file.path(opt$outdir, "sample_summary.tsv"), sep = "\t")

  if (opt$spike && "well" %in% names(D$meta)) {
    pm <- D$meta$platform == "parse"
    sp <- group_spike_screen(D$counts[, pm, drop = FALSE], D$genes, D$meta$well[pm], D$meta$sample[pm], min_fc = opt$spike_fc, log10_p_cut = opt$spike_log10p)
    fwrite(sp$genes, file.path(opt$outdir, "well_spikes.tsv"), sep = "\t")
    fwrite(sp$summary, file.path(opt$outdir, "well_spikes_summary.tsv"), sep = "\t")
    message("well screen: ", nrow(sp$genes), " gene/well pairs flagged across ", nrow(sp$summary), " wells")
  }
  if (opt$thin != "none") {
    target <- if (opt$thin == "auto") as.numeric(quantile(cells$n_umi[cells$qc_pass], 0.10)) else as.numeric(opt$thin)
    th <- thin_counts(D$counts, target)
    message(sprintf("thinning to %.0f UMIs; %d cells are already below the target and stay unchanged", target, sum(th$native)))
    saveRDS(list(counts = th$counts, genes = D$genes, target = target, native = th$native), file.path(opt$outdir, "thinned_counts.rds"))
  }
  if (opt$save_rds) saveRDS(list(counts = D$counts, genes = D$genes, meta = cells), file.path(opt$outdir, "qc_counts.rds"))
  cat(sprintf("%d cells, %d pass QC; tables in %s\n", nrow(cells), sum(cells$qc_pass), opt$outdir))
  0L
}, error = function(e) { cat("run_qc.R: ", conditionMessage(e), "\n", sep = "", file = stderr()); 1L })
quit(status = res, save = "no")
