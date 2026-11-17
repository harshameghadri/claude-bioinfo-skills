# Deterministic synthetic Parse and 10x matrices with planted problems. No real data, no network.
# make_fixture(dir) writes <dir>/parse_A (cells x genes, Parse layout), <dir>/tenx_B (genes x cells, 10x layout)
# and returns the truth (which cell ids were planted with which problem).
suppressPackageStartupMessages({ library(Matrix); library(data.table) })

.write_gz_mtx <- function(m, path) {
  tmp <- tempfile(fileext = ".mtx"); on.exit(unlink(tmp))
  writeMM(as(m, "TsparseMatrix"), tmp)
  con <- gzfile(path, "wb"); on.exit(close(con), add = TRUE, after = FALSE)
  writeLines(readLines(tmp), con)
}
.write_gz_tsv <- function(df, path, header = TRUE, sep = "\t") {
  con <- gzfile(path, "wb"); on.exit(close(con)); write.table(df, con, sep = sep, quote = FALSE, row.names = FALSE, col.names = header)
}

make_gene_table <- function(n_endo = 600) {
  mt_pc <- c("MT-ND1", "MT-ND2", "MT-ND3", "MT-ND4", "MT-ND4L", "MT-ND5", "MT-ND6", "MT-CO1", "MT-CO2", "MT-CO3", "MT-ATP6", "MT-ATP8", "MT-CYB")
  special <- c(mt_pc, "MT-RNR1", "MT-RNR2", "MALAT1", "RN7SK", "RMRP", "RPPH1", "H4C3", "H2AC6", "H3C1", "H1-2", "SPIKEG", "TOPG")
  nm <- c(special, sprintf("GENE%04d", seq_len(n_endo)))
  data.table(gene_id = sprintf("FAKE%05d", seq_along(nm)), gene_name = nm)
}

# Simulate one sample's genes x cells counts. Returns list(counts, planted = named list of column indices).
simulate_counts <- function(genes, n_cells, seed, plant = TRUE, spike_cols = integer(0)) {
  set.seed(seed)
  nm <- genes$gene_name; G <- nrow(genes)
  w <- rlnorm(G, 0, 1.5); names(w) <- nm
  mt_pc <- grep("^MT-(ND|CO|ATP|CYB)", nm); mt_rrna <- which(nm %in% c("MT-RNR1", "MT-RNR2")); mal <- which(nm == "MALAT1")
  top <- which(nm == "TOPG"); spike <- which(nm == "SPIKEG")
  nonmt <- setdiff(seq_len(G), mt_pc)
  wn <- w[nonmt]; wn[match(mt_rrna, nonmt)] <- sum(wn) * 0.03 / 2; wn[match(mal, nonmt)] <- sum(wn) * 0.01
  wn[match(spike, nonmt)] <- median(wn); wn[match(top, nonmt)] <- median(wn)
  wm <- w[mt_pc]
  depth <- round(rlnorm(n_cells, log(4000), 0.25))
  rho <- 0.02; p <- rbeta(n_cells, 0.03 * (1 - rho) / rho, 0.97 * (1 - rho) / rho)
  planted <- list(low_depth = integer(0), high_mt = integer(0), top_gene = integer(0), top_malat1 = integer(0))
  if (plant) {
    planted$low_depth <- 1:10; planted$high_mt <- 11:20; planted$top_gene <- 21:25; planted$top_malat1 <- 26:30
    depth[planted$low_depth] <- 120L
    p[planted$high_mt] <- 0.35
  }
  M <- matrix(0L, G, n_cells, dimnames = list(genes$gene_id, NULL))
  for (j in seq_len(n_cells)) {
    nmt <- rbinom(1, depth[j], p[j])
    pr <- wn
    if (j %in% planted$top_gene) pr[match(top, nonmt)] <- sum(pr) * 0.43     # ~30% of non-mt UMIs
    if (j %in% planted$top_malat1) pr[match(mal, nonmt)] <- sum(pr) * 0.43
    if (j %in% spike_cols) pr[match(spike, nonmt)] <- sum(pr) * 0.05
    M[nonmt, j] <- rmultinom(1, depth[j] - nmt, pr)[, 1]
    if (nmt > 0) M[mt_pc, j] <- rmultinom(1, nmt, wm)[, 1]
  }
  list(counts = as(M, "CsparseMatrix"), planted = planted)
}

make_fixture <- function(dir, n_parse = 400, n_10x = 300) {
  genes <- make_gene_table()
  # --- Parse sample A: 4 round-1 wells x 2 sublibraries, wells A3 carries a planted spike
  wells <- rep(c("A1", "A2", "A3", "A4"), length.out = n_parse)
  spike_cols <- which(wells == "A3" & seq_len(n_parse) > 30)
  A <- simulate_counts(genes, n_parse, seed = 11, spike_cols = spike_cols)
  set.seed(5)
  trip <- unique(data.table(a = sample(1:96, 3 * n_parse, TRUE), b = sample(1:96, 3 * n_parse, TRUE), c = sample(1:96, 3 * n_parse, TRUE)))[seq_len(n_parse)]
  bc_wells <- sprintf("%02d_%02d_%02d__%s", trip$a, trip$b, trip$c, rep(c("sub1", "sub2"), length.out = n_parse))
  pdir <- file.path(dir, "parse_A"); dir.create(pdir, recursive = TRUE, showWarnings = FALSE)
  .write_gz_mtx(t(A$counts), file.path(pdir, "count_matrix.mtx.gz"))                       # Parse: cells x genes
  .write_gz_tsv(data.frame(gene_id = genes$gene_id, gene_name = genes$gene_name, genome = "fake"), file.path(pdir, "all_genes.csv.gz"), sep = ",")
  .write_gz_tsv(data.frame(bc_wells = bc_wells, bc1_well = wells, sample = "pipeline_label", stringsAsFactors = FALSE), file.path(pdir, "cell_metadata.csv.gz"), sep = ",")
  # --- 10x sample B (with an extra non-GEX feature type), genes x cells
  B <- simulate_counts(genes, n_10x, seed = 22, plant = FALSE)
  adt <- Matrix(rpois(2 * n_10x, 3), 2, n_10x, sparse = TRUE)
  Bm <- rbind(B$counts, adt); rownames(Bm) <- NULL
  xdir <- file.path(dir, "tenx_B"); dir.create(xdir, recursive = TRUE, showWarnings = FALSE)
  .write_gz_mtx(Bm, file.path(xdir, "matrix.mtx.gz"))
  set.seed(9); bcs <- unique(replicate(n_10x * 2, paste0(paste(sample(c("A", "C", "G", "T"), 16, TRUE), collapse = ""), "-1")))[seq_len(n_10x)]
  .write_gz_tsv(data.frame(bcs), file.path(xdir, "barcodes.tsv.gz"), header = FALSE)
  feat <- data.frame(id = c(genes$gene_id, "ADT1", "ADT2"), name = c(genes$gene_name, "CD3", "CD19"),
                     type = c(rep("Gene Expression", nrow(genes)), rep("Antibody Capture", 2)))
  .write_gz_tsv(feat, file.path(xdir, "features.tsv.gz"), header = FALSE)
  list(genes = genes, parse_dir = pdir, tenx_dir = xdir, planted = A$planted, spike_cols = spike_cols, wells = wells,
       parse_counts = A$counts, tenx_counts = B$counts, bc_wells = bc_wells)
}
