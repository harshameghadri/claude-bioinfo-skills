# kernel.R - helpers for the stepwise-cluster-labelling skill (Seurat >= 4). Functions only.

rpca_integrate_by_sample <- function(obj, sample_col, features = NULL, n_features = 2000, dims = 30,
                                     regress = NULL, k_filter = NULL, k_weight = NULL, k_score = NULL) {
  # per-sample RPCA integration as in a standard snRNA workflow; returns object with an 'integrated' assay
  suppressPackageStartupMessages(library(Seurat))
  ol <- SplitObject(obj, split.by = sample_col)
  ol <- lapply(ol, function(x) { x <- NormalizeData(x, verbose = FALSE)
    FindVariableFeatures(x, selection.method = "vst", nfeatures = min(n_features, nrow(x)), verbose = FALSE) })
  if (is.null(features)) features <- SelectIntegrationFeatures(object.list = ol, nfeatures = n_features)
  ol <- lapply(ol, function(x) { x <- ScaleData(x, features = features, vars.to.regress = regress, verbose = FALSE)
    RunPCA(x, features = features, npcs = dims, verbose = FALSE) })
  smallest <- min(vapply(ol, ncol, 1L))
  if (is.null(k_filter)) k_filter <- min(200, smallest - 1)
  if (is.null(k_weight)) k_weight <- min(100, smallest - 1)
  if (is.null(k_score)) k_score <- min(30, smallest - 1)
  anchors <- FindIntegrationAnchors(object.list = ol, anchor.features = features, reduction = "rpca",
                                    dims = 1:dims, k.filter = k_filter, k.score = k_score, verbose = FALSE)
  out <- IntegrateData(anchorset = anchors, dims = 1:dims, k.weight = k_weight, verbose = FALSE)
  DefaultAssay(out) <- "integrated"
  message("RPCA: ", length(ol), " samples, ", length(features), " features, smallest sample ", smallest,
          " cells, k.filter ", k_filter, ", k.weight ", k_weight)
  out
}

markers_per_cluster <- function(obj, ident_col = "seurat_clusters", n_per_cluster = 500, logfc = 0.1,
                                assay = "RNA", ncores = 4, seed = 1) {
  # downsampled one-vs-rest positive markers per cluster, in parallel (one-vs-rest, downsampled)
  suppressPackageStartupMessages(library(Seurat))
  DefaultAssay(obj) <- assay
  Idents(obj) <- ident_col
  set.seed(seed)
  sub <- subset(obj, downsample = n_per_cluster)
  if (utils::packageVersion("SeuratObject") >= "5.0.0") sub <- tryCatch(JoinLayers(sub), error = function(e) sub)
  cl <- levels(Idents(sub))
  one <- function(x) { m <- FindMarkers(sub, ident.1 = x, logfc.threshold = logfc, only.pos = TRUE, verbose = FALSE)
    if (!nrow(m)) return(NULL); m$gene <- rownames(m); m$cluster <- as.character(x); rownames(m) <- NULL; m }
  res <- parallel::mclapply(cl, one, mc.cores = ncores)
  do.call(rbind, res[!vapply(res, is.null, TRUE)])
}

cluster_review_table <- function(obj, markers, lineage_markers, ident_col = "seurat_clusters",
                                 sample_col = NULL, count_col = "nCount_RNA", assay = "RNA",
                                 n_top = 10, mix_ratio = 0.5, low_q = 0.5) {
  # one row per cluster: size, median counts, top markers, mean expression per lineage set,
  # suggested lineage and two suggestions to check by eye (mixed_lineage, low_quality)
  suppressPackageStartupMessages(library(Seurat))
  DefaultAssay(obj) <- assay
  cl <- as.character(obj[[ident_col, drop = TRUE]])
  dat <- GetAssayData(obj, assay = assay, layer = "data")
  lm <- lapply(lineage_markers, function(g) intersect(g, rownames(dat)))
  lm <- lm[lengths(lm) > 0]
  lin <- sapply(lm, function(g) Matrix::colMeans(dat[g, , drop = FALSE]))
  if (is.null(dim(lin))) lin <- matrix(lin, ncol = length(lm), dimnames = list(colnames(dat), names(lm)))
  agg <- apply(lin, 2, function(v) tapply(v, cl, mean))
  if (is.null(dim(agg))) agg <- matrix(agg, nrow = 1, dimnames = list(unique(cl), names(lm)))
  cnt <- obj[[count_col, drop = TRUE]]
  med_all <- stats::median(cnt)
  rows <- lapply(rownames(agg), function(k) {
    s <- sort(agg[k, ], decreasing = TRUE)
    top <- markers[markers$cluster == k, ]
    top <- head(top[order(top$p_val_adj, -top$avg_log2FC), "gene"], n_top)
    other_lin_in_top <- names(lm)[vapply(lm, function(g) any(g %in% top), TRUE)]
    mixed <- (length(s) > 1 && s[2] >= mix_ratio * s[1] && s[1] > 0) || length(other_lin_in_top) > 1
    med <- stats::median(cnt[cl == k])
    d <- data.frame(cluster = k, n_cells = sum(cl == k), median_counts = med,
                    suggested_lineage = names(s)[1], second_lineage = if (length(s) > 1) names(s)[2] else NA,
                    second_to_top_ratio = if (length(s) > 1 && s[1] > 0) round(s[2] / s[1], 2) else NA,
                    mixed_lineage = mixed, low_quality = med < low_q * med_all,
                    top_markers = paste(top, collapse = ","), stringsAsFactors = FALSE)
    if (!is.null(sample_col)) { tb <- table(obj[[sample_col, drop = TRUE]][cl == k])
      d$max_sample_share <- round(max(tb) / sum(tb), 2); d$max_sample <- names(tb)[which.max(tb)] }
    d })
  out <- do.call(rbind, rows)
  out <- cbind(out, round(agg[out$cluster, , drop = FALSE], 3))
  rownames(out) <- NULL
  out
}

apply_cluster_names <- function(obj, name_map, ident_col = "seurat_clusters", out_col = "cell.type.ident") {
  # name_map: named character vector cluster -> label (junk labelled explicitly, e.g. 'Fibro_EC_Multiplets', 'Trash')
  cl <- as.character(obj[[ident_col, drop = TRUE]])
  miss <- setdiff(unique(cl), names(name_map))
  if (length(miss)) stop("clusters without a name: ", paste(miss, collapse = ", "))
  obj[[out_col]] <- unname(name_map[cl])
  print(table(obj[[out_col, drop = TRUE]]))
  obj
}

unity_heatmap_matrix <- function(obj, genes, label_col, group_col, subject_col, label_order = NULL,
                                 group_order = NULL, min_cells = 5, assay = "RNA") {
  # pseudobulk mean per label x group x subject (>= min_cells), each gene scaled 0-1 across columns
  suppressPackageStartupMessages(library(Seurat))
  dat <- GetAssayData(obj, assay = assay, layer = "data")
  genes <- genes[genes %in% rownames(dat)]
  md <- data.frame(lab = obj[[label_col, drop = TRUE]], grp = obj[[group_col, drop = TRUE]],
                   sub = obj[[subject_col, drop = TRUE]], stringsAsFactors = FALSE)
  key <- paste(md$lab, md$grp, md$sub, sep = "__")
  n <- table(key); keep <- names(n)[n >= min_cells]
  m <- sapply(keep, function(k) Matrix::rowMeans(dat[genes, key == k, drop = FALSE]))
  if (is.null(dim(m))) m <- matrix(m, ncol = length(keep), dimnames = list(genes, keep))
  ann <- do.call(rbind, strsplit(colnames(m), "__", fixed = TRUE))
  ann <- data.frame(column = colnames(m), cell_type = ann[, 1], group = ann[, 2], subject = ann[, 3],
                    n_cells = as.integer(n[colnames(m)]), stringsAsFactors = FALSE)
  if (is.null(label_order)) label_order <- sort(unique(ann$cell_type))
  if (is.null(group_order)) group_order <- sort(unique(ann$group))
  ann$cell_type <- factor(ann$cell_type, levels = intersect(label_order, unique(ann$cell_type)))
  ann$group <- factor(ann$group, levels = intersect(group_order, unique(ann$group)))
  ann <- ann[order(ann$cell_type, ann$group, ann$subject), ]
  m <- m[, ann$column, drop = FALSE]
  unity <- t(apply(m, 1, function(x) { r <- range(x); if (diff(r) == 0) x * 0 else (x - r[1]) / diff(r) }))
  dropped <- setdiff(names(n), keep)
  if (length(dropped)) message(length(dropped), " label x group x subject combinations below ", min_cells, " cells dropped")
  list(mat = unity, raw = m, annotation = ann)
}

unity_heatmap <- function(um, colours = NULL, file = NULL, width = 10, height = 8, ...) {
  # draws the unity matrix: fixed row order, no clustering, columns split by cell type
  suppressPackageStartupMessages({ library(ComplexHeatmap); library(circlize) })
  if (is.null(colours)) colours <- circlize::colorRamp2(c(0, 0.5, 1), c("#2166AC", "white", "gold2"))
  a <- um$annotation
  ta <- HeatmapAnnotation(cell_type = as.character(a$cell_type), group = as.character(a$group),
                          subject = a$subject, show_legend = c(subject = FALSE), annotation_name_side = "left")
  h <- Heatmap(um$mat, name = "unity", col = colours, cluster_rows = FALSE, cluster_columns = FALSE,
               show_column_names = FALSE, top_annotation = ta, column_split = a$cell_type,
               column_title_rot = 90, use_raster = FALSE, ...)
  if (!is.null(file)) { grDevices::pdf(file, width = width, height = height); draw(h); grDevices::dev.off() }
  invisible(h)
}
