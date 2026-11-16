# function-templates.R
# Ready-to-copy Roxygen2 function templates for the mypkg package
# Copy the template closest to your use case and adapt.

# ============================================================
# TEMPLATE 1: Data loading / IO function
# ============================================================

#' [Short verb phrase — Load, Read, Write, Import, Export ...]
#'
#' [One paragraph description. What does this function do and why?]
#'
#' @param obj A [Seurat::Seurat-class] object with a Spatial assay.
#' @param file `character(1)`. Path to the input file.
#' @param assay `character(1)`. Assay to operate on. Default: `"SCT"`.
#' @param verbose `logical(1)`. Print progress messages. Default: `TRUE`.
#'
#' @return [Describe return value: type, class, dimensions if relevant.]
#'
#' @details
#' [Optional extended description. Use markdown freely.]
#'
#' @examples
#' \dontrun{
#' result <- my_function(obj, file = "path/to/file.rds")
#' }
#'
#' @seealso [related_function()]
#' @family data-io
#'
#' @importFrom Seurat Assays DefaultAssay
#' @export
my_io_function <- function(obj, file, assay = "SCT", verbose = TRUE) {

  .validate_spatial_seurat(obj, assay)

  if (!file.exists(file)) {
    stop("File not found: ", file, call. = FALSE)
  }

  if (verbose) message("Processing: ", file)

  # ... implementation ...

  invisible(obj)
}


# ============================================================
# TEMPLATE 2: Analysis / scoring function (returns modified Seurat)
# ============================================================

#' Compute Spatial Gene Set Scores
#'
#' Scores each spot in a Visium HD object for a collection of gene sets using
#' the AUCell algorithm, storing results as additional metadata columns.
#'
#' @param obj A [Seurat::Seurat-class] object. Must have a normalised assay.
#' @param gene_sets A named `list` of character vectors, where each element
#'   is a gene set (vector of gene symbols) and the name is the pathway name.
#' @param assay `character(1)`. Normalised assay to use. Default: `"SCT"`.
#' @param slot `character(1)`. Assay slot to extract. One of `"data"`,
#'   `"counts"`. Default: `"data"`.
#' @param n_cores `integer(1)`. Number of parallel workers. Default: `1L`.
#' @param verbose `logical(1)`. Print progress. Default: `TRUE`.
#'
#' @return The input Seurat object with gene set scores added to `obj@meta.data`.
#'   Score column names match the names of `gene_sets`.
#'
#' @details
#' Internally uses [AUCell::AUCell_run()] to compute area-under-the-curve
#' enrichment scores per spot. Scores are normalised to [0, 1] range within
#' each gene set.
#'
#' @examples
#' \dontrun{
#' hallmark_sets <- msigdbr::msigdbr(species = "Homo sapiens", category = "H")
#' gene_sets <- split(hallmark_sets$gene_symbol, hallmark_sets$gs_name)
#'
#' obj <- compute_spatial_scores(obj, gene_sets = gene_sets)
#' head(obj@meta.data[, names(gene_sets)[1:3]])
#' }
#'
#' @seealso [run_spatial_gsea()], [plot_pathway_heatmap()]
#' @family scoring
#'
#' @importFrom AUCell AUCell_buildRankings AUCell_run getAUC
#' @importFrom Seurat GetAssayData
#' @export
compute_spatial_scores <- function(obj,
                                    gene_sets,
                                    assay    = "SCT",
                                    slot     = "data",
                                    n_cores  = 1L,
                                    verbose  = TRUE) {

  .validate_spatial_seurat(obj, assay)

  if (!is.list(gene_sets) || is.null(names(gene_sets))) {
    stop("`gene_sets` must be a named list of character vectors.", call. = FALSE)
  }

  expr_mat <- Seurat::GetAssayData(obj, assay = assay, slot = slot)

  if (verbose) message("Building AUCell rankings for ", ncol(expr_mat), " spots ...")

  rankings <- AUCell::AUCell_buildRankings(
    expr_mat,
    nCores  = n_cores,
    plotStats = FALSE
  )

  if (verbose) message("Computing AUC scores for ", length(gene_sets), " gene sets ...")

  auc_scores <- AUCell::AUCell_run(
    rankings,
    geneSets = gene_sets,
    nCores   = n_cores
  )

  score_mat <- t(AUCell::getAUC(auc_scores))   # spots × pathways

  obj <- Seurat::AddMetaData(obj, metadata = as.data.frame(score_mat))

  if (verbose) message("Done. Scores added to metadata.")

  obj
}


# ============================================================
# TEMPLATE 3: Plot / visualisation function (returns ggplot)
# ============================================================

#' Plot Pathway Score as Spatial Heatmap
#'
#' Overlays a pathway enrichment score onto the Visium tissue image as a
#' colour-coded spatial heatmap.
#'
#' @param obj A [Seurat::Seurat-class] object with pathway scores in metadata.
#'   Run [compute_spatial_scores()] first.
#' @param pathway `character(1)`. Name of the pathway column in `obj@meta.data`.
#' @param palette `character(1)`. Viridis palette name. One of `"viridis"`,
#'   `"magma"`, `"plasma"`, `"inferno"`. Default: `"magma"`.
#' @param pt_size `numeric(1)`. Point size for spots. Default: `1.5`.
#' @param title `character(1)` or `NULL`. Plot title. `NULL` uses `pathway`.
#'
#' @return A [ggplot2::ggplot] object. Can be further modified with `+` operators
#'   or passed to [plotly::ggplotly()] for interactivity.
#'
#' @examples
#' \dontrun{
#' p <- plot_spatial_pathway(obj, pathway = "HALLMARK_MYC_TARGETS_V1")
#' print(p)
#'
#' # Make interactive
#' plotly::ggplotly(p)
#' }
#'
#' @seealso [compute_spatial_scores()], [plot_pathway_heatmap()]
#' @family visualisation
#'
#' @importFrom Seurat SpatialFeaturePlot
#' @importFrom ggplot2 scale_fill_viridis_c ggtitle
#' @export
plot_spatial_pathway <- function(obj,
                                  pathway,
                                  palette  = "magma",
                                  pt_size  = 1.5,
                                  title    = NULL) {

  .validate_spatial_seurat(obj)

  if (!pathway %in% colnames(obj@meta.data)) {
    stop("Pathway '", pathway, "' not found in metadata. ",
         "Run compute_spatial_scores() first.", call. = FALSE)
  }

  plot_title <- if (is.null(title)) {
    gsub("_", " ", pathway)   # humanise pathway name
  } else {
    title
  }

  Seurat::SpatialFeaturePlot(
    obj,
    features       = pathway,
    pt.size.factor = pt_size
  ) +
    ggplot2::scale_fill_viridis_c(
      option = palette,
      name   = "AUC score"
    ) +
    ggplot2::ggtitle(plot_title)
}


# ============================================================
# TEMPLATE 4: Internal helper (not exported)
# ============================================================

#' Validate a Spatial Seurat Object
#'
#' @param obj A Seurat object.
#' @param assay `character(1)`. Assay to check existence of. Default: `"Spatial"`.
#'
#' @return Invisibly returns `TRUE`. Stops with informative error if invalid.
#'
#' @keywords internal
.validate_spatial_seurat <- function(obj, assay = "Spatial") {
  if (!inherits(obj, "Seurat")) {
    stop("`obj` must be a Seurat object, got: ", class(obj)[1], call. = FALSE)
  }
  if (!assay %in% Seurat::Assays(obj)) {
    available <- paste(Seurat::Assays(obj), collapse = ", ")
    stop(
      "Assay '", assay, "' not found. Available assays: ", available,
      call. = FALSE
    )
  }
  invisible(TRUE)
}


# ============================================================
# TEMPLATE 5: Summary / stats function (returns data.frame/tibble)
# ============================================================

#' Summarise Spot-Level QC Metrics
#'
#' Returns a tidy `data.frame` of per-cluster QC metric summaries,
#' useful for reporting and table display in Quarto.
#'
#' @param obj A [Seurat::Seurat-class] object with QC metrics computed.
#' @param group_by `character(1)`. Metadata column to group by.
#'   Default: `"seurat_clusters"`.
#' @param metrics `character`. Metadata columns to summarise.
#'   Default: `c("nCount_Spatial", "nFeature_Spatial", "percent.mt")`.
#'
#' @return A `data.frame` with columns: `group`, `metric`, `median`, `mean`, `sd`,
#'   `n_spots`.
#'
#' @examples
#' \dontrun{
#' qc_table <- summarise_qc(obj)
#' DT::datatable(qc_table)
#' }
#'
#' @importFrom dplyr group_by summarise across all_of n
#' @importFrom tidyr pivot_longer
#' @export
summarise_qc <- function(obj,
                          group_by = "seurat_clusters",
                          metrics  = c("nCount_Spatial", "nFeature_Spatial", "percent.mt")) {

  .validate_spatial_seurat(obj)

  meta <- obj@meta.data
  meta$group <- meta[[group_by]]

  meta[, c("group", metrics)] |>
    dplyr::group_by(group) |>
    dplyr::summarise(
      dplyr::across(
        dplyr::all_of(metrics),
        list(
          median = \(x) median(x, na.rm = TRUE),
          mean   = \(x) mean(x, na.rm = TRUE),
          sd     = \(x) sd(x, na.rm = TRUE)
        ),
        .names = "{.col}__{.fn}"
      ),
      n_spots = dplyr::n(),
      .groups = "drop"
    )
}
