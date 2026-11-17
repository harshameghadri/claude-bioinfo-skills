# Offline tests for parse-vs-10x-qc. Synthetic data only. Exit 0 = all passed.
args <- commandArgs(FALSE)
here <- dirname(normalizePath(sub("^--file=", "", grep("^--file=", args, value = TRUE)[1])))
skill <- dirname(here)
source(file.path(here, "fixture_lib.R")); source(file.path(skill, "scripts", "read_matrices.R")); source(file.path(skill, "scripts", "qc_core.R"))

n_fail <- 0L; n_pass <- 0L
check <- function(name, expr) {
  ok <- tryCatch(isTRUE(expr), error = function(e) { cat("  error:", conditionMessage(e), "\n"); FALSE })
  if (ok) n_pass <<- n_pass + 1L else n_fail <<- n_fail + 1L
  cat(sprintf("%s %s\n", if (ok) "ok  " else "FAIL", name))
}
expect_error <- function(expr, pattern) tryCatch({ force(expr); FALSE }, error = function(e) grepl(pattern, conditionMessage(e)))

tmp <- file.path(tempdir(), "fx"); fx <- make_fixture(tmp)
rscript <- file.path(R.home("bin"), "Rscript")
run_cli <- function(...) {
  out <- suppressWarnings(system2(rscript, c(shQuote(file.path(skill, "scripts", "run_qc.R")), ...), stdout = TRUE, stderr = TRUE))
  list(status = attr(out, "status") %||% 0L, out = out)
}
`%||%` <- function(a, b) if (is.null(a)) b else a

cat("-- readers\n")
P <- read_parse(fx$parse_dir, "A"); X <- read_10x(fx$tenx_dir, "B")
check("parse: genes x cells after auto-orientation", identical(dim(P$counts), c(nrow(fx$genes), 400L)))
check("parse: counts equal the simulated truth", all(unname(as.matrix(P$counts)) == unname(as.matrix(fx$parse_counts))))
check("parse: cell_id = sample_bc_wells", identical(P$meta$cell_id, paste0("A_", fx$bc_wells)))
check("parse: sublibrary parsed from text after '__'", identical(P$meta$sublib, rep(c("sub1", "sub2"), length.out = 400)))
check("parse: well taken from bc1_well", identical(P$meta$well, fx$wells))
check("parse: pipeline 'sample' column preserved under another name", "parse_sample" %in% names(P$meta) && all(P$meta$sample == "A"))
check("parse: n_umi equals colSums", all(P$meta$n_umi == colSums(P$counts)))
check("10x: ADT features dropped, genes x cells", identical(dim(X$counts), c(nrow(fx$genes), 300L)))
check("10x: counts equal the simulated truth", all(unname(as.matrix(X$counts)) == unname(as.matrix(fx$tenx_counts))))
check("10x: other feature types selectable", ncol(read_10x(fx$tenx_dir, "B", "Antibody Capture")$counts) == 300L)
check("10x: unknown feature type is an error", expect_error(read_10x(fx$tenx_dir, "B", "Peaks"), "no features of type"))
check("square matrix orientation is refused", expect_error(.orient(Matrix(0, 5, 5, sparse = TRUE), 5, 5, "x"), "square"))
check("wrong annotation size is refused", expect_error(.orient(Matrix(0, 5, 7, sparse = TRUE), 4, 6, "x"), "annotation has"))
check("explicit orientation overrides auto", {
  d <- file.path(tempdir(), "sq"); dir.create(d); file.copy(list.files(fx$parse_dir, full.names = TRUE), d)
  identical(dim(read_parse(d, "A", orientation = "cells_x_genes")$counts), c(nrow(fx$genes), 400L)) })
check("combine_samples refuses different gene tables", {
  Y <- X; Y$genes <- copy(Y$genes)[order(-seq_len(.N))]; expect_error(combine_samples(list(P, Y)), "different gene tables") })
check("combine_samples stacks cells", ncol(combine_samples(list(P, X))$counts) == 700L)

cat("-- metrics\n")
m <- cell_metrics(P$counts, P$genes)
raw <- colSums(P$counts); rr <- colSums(P$counts[P$genes$gene_name %in% c("MT-RNR1", "MT-RNR2"), ])
check("mt-rRNA removed from analysis UMI count", all(m$n_umi == raw - rr) && all(m$n_umi_raw == raw))
check("raw mt-rRNA fraction computed against raw UMIs", all.equal(m$frac_mtrrna, as.numeric(rr / raw)))
check("top gene identified per cell", { j <- 30; m$top_gene[j] == "MALAT1" && m$top_gene_frac[j] > 0.2 })
check("top gene fraction equals brute force", {
  A <- P$counts[!P$genes$gene_name %in% c("MT-RNR1", "MT-RNR2"), ]
  all.equal(m$top_gene_frac, as.numeric(apply(A, 2, max) / colSums(A))) })
check("mouse species uses mouse names", {
  g <- copy(P$genes); g[gene_name == "MT-ND1", gene_name := "mt-Nd1"]; g[gene_name == "MALAT1", gene_name := "Malat1"]
  mm <- cell_metrics(P$counts, g, species = "mouse"); sum(mm$mtpc_umi) > 0 && sum(mm$mtpc_umi) < sum(m$mtpc_umi) })

cat("-- rules\n")
f <- qc_flags(m)
pl <- fx$planted
check("planted low-depth cells flagged (10/10)", sum(f$qc_depth[pl$low_depth]) == 10)
check("planted high-mt cells flagged (10/10)", sum(f$qc_mt[pl$high_mt]) == 10)
check("planted top-gene cells flagged (5/5)", sum(f$qc_top[pl$top_gene]) == 5)
check("MALAT1-dominated cells with typical complexity are NOT flagged", sum(f$qc_top[pl$top_malat1]) == 0)
others <- setdiff(seq_len(400), unlist(pl))
check("false positives are rare (<= 2% of unplanted cells)", mean(f$qc_fail[others]) <= 0.02)
check("qc_pass is the complement of qc_fail", all(f$qc_pass == !f$qc_fail))
check("thresholds table exposes the fit", all(c("umi_floor", "mt_rho", "mt_fit_rounds") %in% attr(f, "thresholds")$parameter))
check("single-pass mt fit (mt_refit = 0) still runs", is.logical(qc_flags(m, mt_refit = 0L)$qc_mt))
check("sensitivity flags only when sample is given", !"v1_fail" %in% names(f) && "v1_fail" %in% names(qc_flags(m, sample = P$meta$well)))
check("method-of-moments fit recovers a simulated beta-binomial", {
  set.seed(3); n <- round(rlnorm(5000, log(3000), 0.3)); rho <- 0.03; pp <- rbeta(5000, 0.05 * (1 - rho) / rho, 0.95 * (1 - rho) / rho)
  ft <- fit_betabinom(rbinom(5000, n, pp), n); abs(ft$p - 0.05) < 0.003 && abs(ft$rho - 0.03) < 0.006 })
check("beta-binomial upper tail is a probability and monotone in x", {
  ft <- list(shape1 = 1, shape2 = 30); p <- betabinom_upper(c(1, 5, 20), rep(1000, 3), ft); all(p >= 0 & p <= 1) && !is.unsorted(rev(p)) })
check("zero-UMI cells do not crash and are flagged", {
  Z <- cbind(P$counts, Matrix(0, nrow(P$counts), 1, sparse = TRUE, dimnames = list(NULL, "empty")))
  mz <- suppressWarnings(cell_metrics(Z, P$genes)); fz <- suppressWarnings(qc_flags(mz)); fz$qc_depth[nrow(fz)] && fz$qc_fail[nrow(fz)] })

cat("-- well screen\n")
sp <- group_spike_screen(P$counts, P$genes, P$meta$well, P$meta$sample)
check("planted spike flagged in its well only", identical(sp$genes$gene_name, "SPIKEG") && identical(sp$genes$group, "A3"))
check("screen summary covers every well", nrow(sp$summary) == 4L && all(sp$summary$n_genes_tested > 0))
check("screen is silent without a spike", { sp0 <- group_spike_screen(P$counts[, -fx$spike_cols], P$genes, P$meta$well[-fx$spike_cols], P$meta$sample[-fx$spike_cols]); nrow(sp0$genes) == 0 })
check("small groups are skipped, not tested", nrow(group_spike_screen(P$counts, P$genes, P$meta$well, P$meta$sample, min_cells = 1000)$summary) == 0)

cat("-- thinning\n")
th <- thin_counts(P$counts, 1000, seed = 1)
n0 <- colSums(P$counts); n1 <- colSums(th$counts)
check("thinning never increases a count", all(th$counts@x <= P$counts@x[match(seq_along(th$counts@x), seq_along(th$counts@x))] | TRUE) && all(as.matrix(th$counts) <= as.matrix(P$counts)))
check("cells below the target are unchanged", all(n1[n0 < 1000] == n0[n0 < 1000]) && identical(th$native, as.numeric(n0) < 1000))
check("cells above the target land near it (mean within 1%, each within 15%)", abs(mean(n1[n0 > 3000]) / 1000 - 1) < 0.01 && all(abs(n1[n0 > 3000] / 1000 - 1) < 0.15))
check("thinning is reproducible for a seed", identical(thin_counts(P$counts, 1000, seed = 1)$counts, th$counts))

cat("-- command line\n")
out <- file.path(tempdir(), "cli")
r <- run_cli("--parse", paste0("A=", fx$parse_dir), "--10x", paste0("B=", fx$tenx_dir), "--outdir", out, "--sensitivity", "--thin-target", "auto", "--save-rds")
check("CLI exits 0 on valid input", r$status == 0L)
cq <- if (file.exists(file.path(out, "cell_qc.tsv"))) fread(file.path(out, "cell_qc.tsv")) else data.table()
check("cell_qc.tsv has one row per cell, both platforms", nrow(cq) == 700L && setequal(unique(cq$platform), c("parse", "10x")))
check("CLI flags agree with the library call (Parse sample, pooled with 10x)", {
  all(cq[sample == "A"]$qc_depth[pl$low_depth]) && all(cq[sample == "A"]$qc_mt[pl$high_mt]) })
check("sample_summary and thresholds written", all(file.exists(file.path(out, c("sample_summary.tsv", "thresholds.tsv", "well_spikes.tsv", "well_spikes_summary.tsv", "thinned_counts.rds", "qc_counts.rds")))))
check("sensitivity flags present", all(c("v1_depth", "v1_genes", "v1_mt", "v1_fail") %in% names(cq)))
check("well screen found the planted spike via CLI", { w <- fread(file.path(out, "well_spikes.tsv")); nrow(w) == 1 && w$gene_name == "SPIKEG" && w$group == "A3" })
check("10x cells carry no well/sublib values", all(is.na(cq[platform == "10x"]$well)))
r2 <- run_cli("--parse", paste0("A=", fx$parse_dir, "@lineX"), "--parse", paste0("A2=", fx$parse_dir, "@lineY"), "--outdir", file.path(tempdir(), "cli2"), "--no-spike-screen")
check("pools get separate thresholds", r2$status == 0L && nrow(fread(file.path(tempdir(), "cli2", "thresholds.tsv"))[parameter == "umi_floor"]) == 2L)
check("--help exits 0", run_cli("--help")$status == 0L)
check("no arguments exit 2", run_cli()$status == 2L)
check("unknown option exits 2", run_cli("--bogus")$status == 2L)
check("missing --outdir exits 2", run_cli("--parse", paste0("A=", fx$parse_dir))$status == 2L)
check("bad --species exits 2", run_cli("--parse", paste0("A=", fx$parse_dir), "--outdir", out, "--species", "yeast")$status == 2L)
check("missing directory exits 1", run_cli("--parse", "A=/nonexistent/dir", "--outdir", out)$status == 1L)
check("duplicate sample names exit 1", run_cli("--parse", paste0("A=", fx$parse_dir), "--10x", paste0("A=", fx$tenx_dir), "--outdir", out)$status == 1L)

cat("-- optional doublet script (scDblFinder is not required for these tests)\n")
dscript <- shQuote(file.path(skill, "scripts", "doublets_scdblfinder.R"))
d_status <- function(...) { o <- suppressWarnings(system2(rscript, c(dscript, ...), stdout = TRUE, stderr = TRUE)); attr(o, "status") %||% 0L }
check("doublet script --help exits 0", d_status("--help") == 0L)
check("doublet script: no arguments exit 2", d_status() == 2L)
check("doublet script: unknown option exits 2", d_status("--bogus", "x") == 2L)
check("doublet script exits 3 when scDblFinder is missing (skipped if installed)",
      requireNamespace("scDblFinder", quietly = TRUE) || d_status("--qc-rds", file.path(out, "qc_counts.rds"), "--outdir", file.path(tempdir(), "dbl")) == 3L)

cat(sprintf("\n%d passed, %d failed\n", n_pass, n_fail))
quit(status = if (n_fail) 1L else 0L, save = "no")
