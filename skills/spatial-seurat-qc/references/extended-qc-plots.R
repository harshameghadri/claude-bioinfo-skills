# extended-qc-plots.R
# Additional diagnostic visualisations for Visium HD QC
# Source after running the core QC pipeline in SKILL.md

library(ggplot2)
library(patchwork)
library(dplyr)

# -------------------------------------------------------------------
# 1. Scatter: nCount vs nFeature coloured by percent.mt
# -------------------------------------------------------------------
plot_count_feature_scatter <- function(obj) {
  df <- data.frame(
    nCount    = obj$nCount_Spatial,
    nFeature  = obj$nFeature_Spatial,
    pct_mt    = obj$percent.mt
  )

  ggplot(df, aes(x = nCount, y = nFeature, colour = pct_mt)) +
    geom_point(size = 0.3, alpha = 0.4) +
    scale_colour_viridis_c(option = "magma", name = "% MT") +
    scale_x_log10() +
    scale_y_log10() +
    labs(title = "UMI vs Genes per spot", x = "nCount (log10)", y = "nFeature (log10)") +
    theme_minimal()
}

# -------------------------------------------------------------------
# 2. QC metric histograms with threshold lines
# -------------------------------------------------------------------
plot_qc_histograms <- function(obj,
                                count_lo  = 100,  count_hi = 50000,
                                feat_lo   = 50,
                                mt_hi     = 25) {

  df <- data.frame(
    nCount   = obj$nCount_Spatial,
    nFeature = obj$nFeature_Spatial,
    pct_mt   = obj$percent.mt
  )

  p1 <- ggplot(df, aes(x = nCount)) +
    geom_histogram(bins = 100, fill = "#4682B4", colour = NA, alpha = 0.8) +
    geom_vline(xintercept = c(count_lo, count_hi), colour = "red", linetype = "dashed") +
    scale_x_log10() +
    labs(title = "nCount distribution", x = "nCount (log10)", y = "Spots") +
    theme_minimal()

  p2 <- ggplot(df, aes(x = nFeature)) +
    geom_histogram(bins = 100, fill = "#2E8B57", colour = NA, alpha = 0.8) +
    geom_vline(xintercept = feat_lo, colour = "red", linetype = "dashed") +
    scale_x_log10() +
    labs(title = "nFeature distribution", x = "nFeature (log10)", y = "Spots") +
    theme_minimal()

  p3 <- ggplot(df, aes(x = pct_mt)) +
    geom_histogram(bins = 100, fill = "#CD853F", colour = NA, alpha = 0.8) +
    geom_vline(xintercept = mt_hi, colour = "red", linetype = "dashed") +
    labs(title = "% Mitochondrial", x = "percent.mt", y = "Spots") +
    theme_minimal()

  p1 | p2 | p3
}

# -------------------------------------------------------------------
# 3. Spatial heatmap of log10(nCount) — spots coloured by library size
# -------------------------------------------------------------------
plot_spatial_library_size <- function(obj) {
  SpatialFeaturePlot(
    obj,
    features = "nCount_Spatial",
    pt.size.factor = 1.2
  ) +
    scale_fill_viridis_c(option = "plasma", trans = "log10") +
    ggtitle("Library size (log10 nCount) across tissue")
}

# -------------------------------------------------------------------
# 4. QC before/after summary table
# -------------------------------------------------------------------
qc_before_after_summary <- function(obj_before, obj_after) {
  tibble::tibble(
    Metric         = c("Spots", "Median nCount", "Median nFeature", "Median % MT"),
    Before         = c(
      ncol(obj_before),
      median(obj_before$nCount_Spatial),
      median(obj_before$nFeature_Spatial),
      round(median(obj_before$percent.mt), 2)
    ),
    After          = c(
      ncol(obj_after),
      median(obj_after$nCount_Spatial),
      median(obj_after$nFeature_Spatial),
      round(median(obj_after$percent.mt), 2)
    ),
    `% Retained`   = c(
      round(ncol(obj_after) / ncol(obj_before) * 100, 1),
      NA, NA, NA
    )
  )
}

# -------------------------------------------------------------------
# 5. Cluster composition barplot (post-clustering)
# -------------------------------------------------------------------
plot_cluster_composition <- function(obj, group_var = "seurat_clusters") {
  df <- as.data.frame(table(obj@meta.data[[group_var]])) %>%
    setNames(c("Cluster", "Spots")) %>%
    mutate(Pct = Spots / sum(Spots) * 100)

  ggplot(df, aes(x = reorder(Cluster, -Spots), y = Pct, fill = Cluster)) +
    geom_col(show.legend = FALSE) +
    labs(title = "Spot composition by cluster",
         x = "Cluster", y = "% of spots") +
    theme_minimal() +
    theme(axis.text.x = element_text(angle = 45, hjust = 1))
}
