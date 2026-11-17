# qc_core.R - platform-agnostic cell QC for single-cell RNA-seq count matrices (genes x cells dgCMatrix).
#
# Rules (defaults are the ones used in the source analysis of Parse Evercode data; every threshold is an argument):
#   depth / genes : log10 UMI (log10 detected genes) below  median - k*MAD  of the pooled cells        (k = 4)
#   mt            : mitochondrial PROTEIN-CODING excess: upper-tail beta-binomial P <= alpha given each cell's UMI count
#                   (method-of-moments overdispersion; the fit starts without cells above median + 5 MAD and is refitted without flagged cells; alpha = 0.001)
#   top gene      : one gene > 20% of UMIs, unless that gene is MALAT1 and the cell's complexity is typical (within 2 MAD)
#   mt-rRNA is removed from the analysis matrix BEFORE depth/gene counts (random-hexamer/total-RNA-like protocols such as Parse
#   capture a lot of it and it would otherwise dominate depth).
# No fixed percent.mt cut-off is used. A per-sample 3-MAD variant is available as a sensitivity analysis (flags only).
#
# Depends on Matrix, data.table, and VGAM (pbetabinom.ab). Source this file:  source("scripts/qc_core.R")
suppressPackageStartupMessages({ library(Matrix); library(data.table) })

MT_PC_GENES <- list(
  human = c("MT-ND1", "MT-ND2", "MT-ND3", "MT-ND4", "MT-ND4L", "MT-ND5", "MT-ND6", "MT-CO1", "MT-CO2", "MT-CO3", "MT-ATP6", "MT-ATP8", "MT-CYB"),
  mouse = c("mt-Nd1", "mt-Nd2", "mt-Nd3", "mt-Nd4", "mt-Nd4l", "mt-Nd5", "mt-Nd6", "mt-Co1", "mt-Co2", "mt-Co3", "mt-Atp6", "mt-Atp8", "mt-Cytb"))
MT_RRNA_GENES <- list(human = c("MT-RNR1", "MT-RNR2"), mouse = c("mt-Rnr1", "mt-Rnr2"))
MALAT1 <- list(human = "MALAT1", mouse = "Malat1")

# Row indices of genes by name (gene_name table row-aligned with the matrix). Duplicated names: all copies are included.
.idx <- function(genes, names) which(genes$gene_name %in% names)

# Median/MAD floor on a log10 scale. k MADs below the median.
mad_floor <- function(x, k = 4) { m <- median(x); s <- mad(x); c(median = m, mad = s, floor = m - k * s) }

# Beta-binomial fit (method of moments) to x successes out of n trials per cell. Returns p, rho and shape parameters.
fit_betabinom <- function(x, n) {
  stopifnot(length(x) == length(n), all(n > 0), all(x <= n))
  p <- sum(x) / sum(n)
  chi2 <- sum((x - n * p)^2 / (n * p * (1 - p)))
  rho <- max((chi2 - length(n)) / sum(n - 1), 1e-6)
  list(p = p, chi2 = chi2, rho = rho, shape1 = p * (1 - rho) / rho, shape2 = (1 - p) * (1 - rho) / rho)
}

# P(X >= x | n) under the fitted beta-binomial (upper tail, includes x).
betabinom_upper <- function(x, n, fit) {
  if (!requireNamespace("VGAM", quietly = TRUE)) stop("package VGAM is required for the mitochondrial rule", call. = FALSE)
  1 - VGAM::pbetabinom.ab(x - 1, size = n, shape1 = fit$shape1, shape2 = fit$shape2)
}

# Per-cell metrics on the analysis matrix (mt-rRNA removed). counts: genes x cells; genes: data.table(gene_id, gene_name).
cell_metrics <- function(counts, genes, species = c("human", "mouse"), exclude_names = NULL, fraction_genes = NULL) {
  species <- match.arg(species)
  stopifnot(nrow(counts) == nrow(genes))
  drop <- .idx(genes, c(MT_RRNA_GENES[[species]], exclude_names))
  keep <- setdiff(seq_len(nrow(counts)), drop)
  A <- counts[keep, , drop = FALSE]; ga <- genes[keep]
  n_raw <- as.numeric(colSums(counts))
  n_umi <- as.numeric(colSums(A))
  n_genes <- as.numeric(colSums(A > 0))
  mtpc <- as.numeric(colSums(A[.idx(ga, MT_PC_GENES[[species]]), , drop = FALSE]))
  mtrrna <- if (length(drop)) as.numeric(colSums(counts[.idx(genes, MT_RRNA_GENES[[species]]), , drop = FALSE])) else rep(0, ncol(counts))
  # top gene per cell (largest count) without densifying: walk the dgC triplets
  dt <- data.table(col = rep(seq_len(ncol(A)), diff(A@p)), row = A@i + 1L, x = A@x)
  top <- dt[order(col, -x)][!duplicated(col)]
  top_count <- numeric(ncol(A)); top_count[top$col] <- top$x
  top_gene <- rep(NA_character_, ncol(A)); top_gene[top$col] <- ga$gene_name[top$row]
  out <- data.table(cell_id = colnames(counts), n_umi_raw = n_raw, n_umi = n_umi, n_genes = n_genes, mtpc_umi = mtpc,
                    frac_mtpc = ifelse(n_umi > 0, mtpc / n_umi, NA_real_), frac_mtrrna = ifelse(n_raw > 0, mtrrna / n_raw, NA_real_),
                    top_gene = top_gene, top_gene_frac = ifelse(n_umi > 0, top_count / n_umi, NA_real_),
                    top_is_malat1 = !is.na(top_gene) & tolower(top_gene) == tolower(MALAT1[[species]]))
  out[, complexity := ifelse(n_umi > 1 & n_genes > 0, log10(n_genes) / log10(n_umi), NA_real_)]
  out[, `:=`(log10_umi = log10(pmax(n_umi, 1)), log10_genes = log10(pmax(n_genes, 1)))]
  for (nm in names(fraction_genes)) {   # optional extra fractions, e.g. list(RN7SK = "RN7SK", histone = c("H4C3", ...))
    out[[paste0(nm, "_frac")]] <- ifelse(n_umi > 0, as.numeric(colSums(A[.idx(ga, fraction_genes[[nm]]), , drop = FALSE])) / n_umi, NA_real_)
  }
  out[]
}

# Apply the QC rules. m: output of cell_metrics (all cells of one dataset; thresholds are pooled over them).
# sample: optional vector (same order) enabling the per-sample sensitivity flags.
qc_flags <- function(m, k = 4, mt_alpha = 0.001, top_frac = 0.20, top_mad = 2, sample = NULL, mt_refit = 3L) {
  m <- copy(m)
  ok <- m$n_umi > 0 & m$n_genes > 0
  if (!all(ok)) warning(sum(!ok), " cell(s) have zero UMIs after removing mt-rRNA; flagged as depth failures")
  d <- mad_floor(m$log10_umi[ok], k); g <- mad_floor(m$log10_genes[ok], k)
  m[, qc_depth := !ok | log10_umi < d[["floor"]]]
  m[, qc_genes := !ok | log10_genes < g[["floor"]]]
  # Beta-binomial null for mt protein-coding UMIs. Method-of-moments is not outlier-robust: a few percent of
  # high-mt cells inflate rho and hide themselves. So the null is refitted without cells that were just flagged
  # (mt_refit rounds; 0 = single pass). Cells failing depth/genes floors do not enter the first fit.
  use <- ok & !m$qc_depth & !m$qc_genes
  if (sum(use) < 20) { warning("fewer than 20 cells for the mitochondrial null; using all cells with UMIs"); use <- ok }
  fr <- m$frac_mtpc; s0 <- mad(fr[use])
  if (is.finite(s0) && s0 > 0) use <- use & fr <= median(fr[use]) + 5 * s0     # robust start: heavy outliers must not set the null
  m[, mt_upper_p := NA_real_]
  rounds <- 0L
  repeat {
    fit <- fit_betabinom(m$mtpc_umi[use], m$n_umi[use])
    m[ok, mt_upper_p := betabinom_upper(mtpc_umi, n_umi, fit)]
    hit <- ok & m$mtpc_umi > 0 & m$mt_upper_p <= mt_alpha
    nxt_use <- use & !hit
    if (rounds >= mt_refit || sum(nxt_use) < 20 || identical(nxt_use, use)) break
    use <- nxt_use; rounds <- rounds + 1L
  }
  m[, qc_mt := hit]
  cm <- mad_floor(m$complexity[ok], 1)
  m[, qc_top := ok & top_gene_frac > top_frac & !(top_is_malat1 & abs(complexity - cm[["median"]]) <= top_mad * cm[["mad"]])]
  m[, qc_fail := qc_depth | qc_genes | qc_mt | qc_top]
  m[, qc_pass := !qc_fail]
  if (!is.null(sample)) {   # sensitivity: per-sample 3 MAD (flags only, not applied)
    stopifnot(length(sample) == nrow(m))
    m[, .s := sample]
    side <- function(x, hi) { md <- median(x); s <- mad(x); if (hi) x > md + 3 * s else x < md - 3 * s }
    m[, `:=`(v1_depth = side(log10_umi, FALSE), v1_genes = side(log10_genes, FALSE), v1_mt = side(frac_mtpc, TRUE)), by = .s]
    m[, v1_fail := v1_depth | v1_genes | v1_mt | qc_top][, .s := NULL]
  }
  thr <- data.table(parameter = c("n_cells", "log10_umi_median", "log10_umi_mad", "umi_floor", "log10_genes_median", "log10_genes_mad", "genes_floor",
                                  "mt_pooled_fraction", "mt_chi2", "mt_rho", "mt_shape1", "mt_shape2", "mt_fit_rounds", "mt_fit_cells", "complexity_median", "complexity_mad", "k", "mt_alpha", "top_frac"),
                    value = c(nrow(m), d[["median"]], d[["mad"]], 10^d[["floor"]], g[["median"]], g[["mad"]], 10^g[["floor"]], fit$p, fit$chi2, fit$rho, fit$shape1, fit$shape2, rounds, sum(use),
                              cm[["median"]], cm[["mad"]], k, mt_alpha, top_frac))
  attr(m, "thresholds") <- thr
  m
}

# Well-spike (or any group-specific contamination) screen. For each group of cells (e.g. Parse round-1 well) and gene:
# exact one-sided binomial test of the gene's counts in the group against the other groups of the same sample, plus fold change.
# Flag: fold change >= min_fc and log10 p < log10_p_cut. counts: genes x cells; group: vector over cells; sample: vector over cells.
group_spike_screen <- function(counts, genes, group, sample, min_fc = 5, log10_p_cut = -20, min_cells = 20) {
  stopifnot(ncol(counts) == length(group), length(group) == length(sample))
  res <- list(); summ <- list()
  for (s in unique(sample)) for (w in sort(unique(group[sample == s]))) {
    inw <- sample == s & group == w; ino <- sample == s & group != w
    if (sum(inw) < min_cells || sum(ino) < min_cells) next
    a <- Matrix::rowSums(counts[, inw, drop = FALSE]); b <- Matrix::rowSums(counts[, ino, drop = FALSE])
    lw <- sum(a); lo <- sum(b); k <- a + b; ok <- which(a > 0)
    lp <- rep(NA_real_, nrow(counts))
    lp[ok] <- pbinom(a[ok] - 1, k[ok], lw / (lw + lo), lower.tail = FALSE, log.p = TRUE) / log(10)
    fc <- ((a + 0.5) / lw) / ((b + 0.5) / lo)
    hit <- which(!is.na(lp) & lp < log10_p_cut & fc >= min_fc)
    if (length(hit)) res[[paste(s, w)]] <- data.table(sample = s, group = w, gene_id = genes$gene_id[hit], gene_name = genes$gene_name[hit],
                                                      count_group = a[hit], count_other = b[hit], fold_change = fc[hit], log10_p = lp[hit])
    summ[[paste(s, w)]] <- data.table(sample = s, group = w, n_cells = sum(inw), n_cells_other = sum(ino), n_genes_tested = length(ok), n_flagged = length(hit))
  }
  list(genes = rbindlist(res), summary = rbindlist(summ))
}

# Binomial depth thinning: each UMI kept with probability min(1, target / n_umi_cell). Cells below the target stay unchanged.
# Used to separate depth effects from real signal (for example in doublet calls). Base R only; seed for reproducibility.
thin_counts <- function(counts, target, seed = 1L) {
  set.seed(seed)
  n <- as.numeric(colSums(counts))
  prop <- pmin(1, target / pmax(n, 1))
  col <- rep(seq_len(ncol(counts)), diff(counts@p))
  th <- counts
  th@x <- as.numeric(rbinom(length(counts@x), as.integer(counts@x), prop[col]))
  th <- drop0(th)
  list(counts = th, prop = prop, native = n < target)
}
