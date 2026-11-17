# read_matrices.R - read Parse Evercode (split-pipe) and 10x Genomics matrices into one common structure.
#
# Returns list(counts = genes x cells dgCMatrix (rownames gene_id, colnames cell_id),
#              genes  = data.table(gene_id, gene_name),
#              meta   = data.table(cell_id, sample, platform, [well, sublib for Parse], n_umi, n_genes)).
# Orientation is the classic trap: Parse count_matrix.mtx(.gz) is cells x genes, 10x matrix.mtx(.gz) is genes x cells.
# Both are detected from the matrix dimensions against the gene and barcode tables, not assumed.
#
# Depends on Matrix and data.table only. Source this file:  source("scripts/read_matrices.R")
suppressPackageStartupMessages({ library(Matrix); library(data.table) })

.read_mtx <- function(path) {
  # gzfile() handles .gz and plain files; readMM() on a gz path alone does not on every platform
  con <- gzfile(path, "rb"); on.exit(close(con))
  readMM(con)
}

# fread() reads .gz files only when R.utils is installed; go through a gzfile connection so no extra package is needed.
.fread_any <- function(path, ...) {
  if (!grepl("\\.gz$", path)) return(fread(path, ...))
  con <- gzfile(path, "rt"); on.exit(close(con))
  fread(text = readLines(con), ...)
}

.find_file <- function(dir, candidates) {
  hit <- file.path(dir, candidates)[file.exists(file.path(dir, candidates))]
  if (!length(hit)) stop("none of ", paste(candidates, collapse = ", "), " found in ", dir, call. = FALSE)
  hit[1]
}

# Orient a matrix to genes x cells using the number of genes and cells known from the annotation tables.
.orient <- function(m, n_genes, n_cells, what) {
  if (nrow(m) == n_genes && ncol(m) == n_cells && !(n_genes == n_cells)) return(m)
  if (nrow(m) == n_cells && ncol(m) == n_genes && !(n_genes == n_cells)) return(t(m))
  if (n_genes == n_cells && nrow(m) == n_genes) stop(what, ": square matrix (", n_genes, " genes = ", n_cells,
    " cells); orientation cannot be inferred, pass orientation = 'cells_x_genes' or 'genes_x_cells'", call. = FALSE)
  stop(what, ": matrix is ", nrow(m), " x ", ncol(m), " but annotation has ", n_genes, " genes and ", n_cells, " cells", call. = FALSE)
}

# Parse Evercode delivery directory, e.g. <delivery>/<sample>/DGE_filtered (or DGE_unfiltered):
#   count_matrix.mtx.gz (cells x genes), all_genes.csv.gz (gene_id, gene_name), cell_metadata.csv.gz (bc_wells, bc1_well, ...)
read_parse <- function(dir, sample, orientation = c("auto", "cells_x_genes", "genes_x_cells")) {
  orientation <- match.arg(orientation)
  sname <- sample   # keep out of data.table's column scope: Parse metadata may carry its own 'sample' column
  genes <- .fread_any(.find_file(dir, c("all_genes.csv.gz", "all_genes.csv")))
  cmeta <- .fread_any(.find_file(dir, c("cell_metadata.csv.gz", "cell_metadata.csv")))
  for (col in c("gene_id", "gene_name")) if (!col %in% names(genes)) stop("all_genes.csv lacks column ", col, call. = FALSE)
  if (!"bc_wells" %in% names(cmeta)) stop("cell_metadata.csv lacks column bc_wells", call. = FALSE)
  m <- .read_mtx(.find_file(dir, c("count_matrix.mtx.gz", "count_matrix.mtx")))
  m <- switch(orientation, auto = .orient(m, nrow(genes), nrow(cmeta), "Parse matrix"),
              cells_x_genes = t(m), genes_x_cells = m)
  m <- as(m, "CsparseMatrix")
  stopifnot(nrow(m) == nrow(genes), ncol(m) == nrow(cmeta))
  if ("sample" %in% names(cmeta)) setnames(cmeta, "sample", "parse_sample")
  cmeta[, cell_id := paste0(sname, "_", bc_wells)]
  cmeta[, sample := sname]
  cmeta[, platform := "parse"]
  cmeta[, sublib := sub(".*__", "", bc_wells)]
  if ("bc1_well" %in% names(cmeta)) cmeta[, well := bc1_well]
  if (anyDuplicated(cmeta$cell_id)) stop("duplicated cell ids in ", dir, call. = FALSE)
  if (anyDuplicated(genes$gene_id)) stop("duplicated gene_id in all_genes.csv of ", dir, call. = FALSE)
  rownames(m) <- genes$gene_id; colnames(m) <- cmeta$cell_id
  cmeta[, n_umi := as.numeric(colSums(m))]
  cmeta[, n_genes := as.numeric(colSums(m > 0))]
  list(counts = m, genes = genes[, .(gene_id, gene_name)], meta = cmeta[])
}

# 10x Genomics matrix directory (Cell Ranger 'filtered_feature_bc_matrix' or 'raw_feature_bc_matrix'):
#   matrix.mtx(.gz), barcodes.tsv(.gz), features.tsv(.gz) (id, name, type) or genes.tsv (id, name) in older versions.
read_10x <- function(dir, sample, feature_type = "Gene Expression") {
  bc <- .fread_any(.find_file(dir, c("barcodes.tsv.gz", "barcodes.tsv")), header = FALSE)
  ft <- .fread_any(.find_file(dir, c("features.tsv.gz", "genes.tsv.gz", "features.tsv", "genes.tsv")), header = FALSE)
  if (ncol(ft) < 2) stop("features/genes file needs at least id and name columns", call. = FALSE)
  setnames(ft, 1:2, c("gene_id", "gene_name"))
  if (ncol(ft) >= 3) setnames(ft, 3, "feature_type") else ft[, feature_type := "Gene Expression"]
  m <- .orient(.read_mtx(.find_file(dir, c("matrix.mtx.gz", "matrix.mtx"))), nrow(ft), nrow(bc), "10x matrix")
  m <- as(m, "CsparseMatrix")
  keep <- ft$feature_type == feature_type
  if (!any(keep)) stop("no features of type '", feature_type, "' (available: ", paste(unique(ft$feature_type), collapse = ", "), ")", call. = FALSE)
  if (!all(keep)) message("read_10x: keeping ", sum(keep), " of ", nrow(ft), " features of type '", feature_type, "'")
  m <- m[keep, , drop = FALSE]; ft <- ft[keep]
  if (anyDuplicated(ft$gene_id)) stop("duplicated gene_id in features file of ", dir, call. = FALSE)
  sname <- sample
  cell_id <- paste0(sname, "_", bc$V1)
  rownames(m) <- ft$gene_id; colnames(m) <- cell_id
  meta <- data.table(cell_id = cell_id, sample = sname, platform = "10x", barcode = bc$V1)
  meta[, n_umi := as.numeric(colSums(m))]
  meta[, n_genes := as.numeric(colSums(m > 0))]
  list(counts = m, genes = ft[, .(gene_id, gene_name)], meta = meta[])
}

# Combine several read_*() results (same gene set required). Samples keep their own metadata columns (others filled with NA).
combine_samples <- function(lst) {
  g1 <- lst[[1]]$genes$gene_id
  for (x in lst) if (!identical(x$genes$gene_id, g1)) stop("samples have different gene tables; subset to a common gene set first", call. = FALSE)
  list(counts = do.call(cbind, lapply(lst, `[[`, "counts")), genes = lst[[1]]$genes,
       meta = rbindlist(lapply(lst, `[[`, "meta"), fill = TRUE))
}
