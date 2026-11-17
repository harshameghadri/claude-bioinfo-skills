#!/usr/bin/env Rscript
# doublets_scdblfinder.R - OPTIONAL, informational doublet calls on native and depth-thinned counts (scDblFinder, per sample).
# Needs Bioconductor packages scDblFinder and SingleCellExperiment. Exit codes: 0 ok, 1 error, 2 usage, 3 package missing.
#
# Why both: doublet scores track sequencing depth. If calls on native counts fall to ~0 after thinning to a common depth,
# they were a depth effect, not doublets. Calls are NOT used to filter cells by run_qc.R.
args <- commandArgs(trailingOnly = TRUE)
usage <- function() cat("Usage: Rscript doublets_scdblfinder.R --qc-rds qc_counts.rds --thinned-rds thinned_counts.rds --outdir DIR [--seed N]
  --qc-rds       qc_counts.rds written by run_qc.R --save-rds
  --thinned-rds  thinned_counts.rds written by run_qc.R --thin-target (optional; without it only native calls are made)
  --outdir       output directory: doublets.tsv (per cell), doublets_summary.tsv (per sample, native vs thinned)
", file = stdout())
fail <- function(msg, code = 1L) { cat("doublets_scdblfinder.R: ", msg, "\n", sep = "", file = stderr()); quit(status = code, save = "no") }
if (!length(args) || any(args %in% c("-h", "--help"))) { usage(); quit(status = if (length(args)) 0L else 2L, save = "no") }
o <- list(qc = NULL, thin = NULL, out = NULL, seed = 1L); i <- 1L
while (i <= length(args)) {
  if (i == length(args)) fail(paste("missing value after", args[i]), 2L)
  v <- args[i + 1L]
  switch(args[i], "--qc-rds" = o$qc <- v, "--thinned-rds" = o$thin <- v, "--outdir" = o$out <- v, "--seed" = o$seed <- as.integer(v), fail(paste("unknown argument:", args[i]), 2L))
  i <- i + 2L
}
if (is.null(o$qc) || is.null(o$out)) fail("--qc-rds and --outdir are required", 2L)
for (p in c("scDblFinder", "SingleCellExperiment")) if (!requireNamespace(p, quietly = TRUE)) fail(paste0("package ", p, " is not installed (BiocManager::install('", p, "'))"), 3L)

status <- tryCatch({
  suppressPackageStartupMessages({ library(Matrix); library(data.table); library(SingleCellExperiment) })
  Q <- readRDS(o$qc); meta <- as.data.table(Q$meta)
  keep <- meta$qc_pass
  call_set <- function(counts, label) {
    sce <- SingleCellExperiment(assays = list(counts = counts[, keep, drop = FALSE]), colData = data.frame(sample = meta$sample[keep], row.names = meta$cell_id[keep]))
    set.seed(o$seed)
    sce <- scDblFinder::scDblFinder(sce, samples = "sample", verbose = FALSE)
    d <- data.table(cell_id = colnames(sce), class = as.character(sce$scDblFinder.class), score = sce$scDblFinder.score)
    setnames(d, c("class", "score"), paste0(label, c("_class", "_score"))); d
  }
  res <- call_set(Q$counts, "native")
  if (!is.null(o$thin)) { Tt <- readRDS(o$thin); res <- merge(res, call_set(Tt$counts, "thinned"), by = "cell_id") }
  res <- merge(meta[, .(cell_id, sample, n_umi)], res, by = "cell_id")
  dir.create(o$out, showWarnings = FALSE, recursive = TRUE)
  fwrite(res, file.path(o$out, "doublets.tsv"), sep = "\t", na = "NA")
  summ <- res[, c(list(n_cells = .N, median_umi = median(n_umi), native_doublet_pct = round(100 * mean(native_class == "doublet"), 2)),
                  if ("thinned_class" %in% names(res)) list(thinned_doublet_pct = round(100 * mean(thinned_class == "doublet"), 2))), by = sample]
  fwrite(summ, file.path(o$out, "doublets_summary.tsv"), sep = "\t")
  print(summ); 0L
}, error = function(e) { cat("doublets_scdblfinder.R: ", conditionMessage(e), "\n", sep = "", file = stderr()); 1L })
quit(status = status, save = "no")
