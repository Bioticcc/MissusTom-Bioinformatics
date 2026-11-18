# Seurat import and QC helpers, kept apart from the analysis so they can be tested alone.
# The input object is only read. Raw counts and confirmed metadata are copied from it.
read_seurat_input <- function(path, assay_name, columns) {
    object <- readRDS(path)
    if (!inherits(object, "Seurat")) stop("The input .rds must contain one Seurat object")
    object <- suppressMessages(SeuratObject::UpdateSeuratObject(object))
    if (!assay_name %in% SeuratObject::Assays(object)) {
        stop("Assay '", assay_name, "' is not in the object. Available: ",
             paste(SeuratObject::Assays(object), collapse = ", "))
    }
    assay <- object[[assay_name]]
    count_layers <- SeuratObject::Layers(assay, search = "counts")
    if (!length(count_layers)) stop("Assay '", assay_name, "' has no raw counts layer")
    # Objects split by sample keep one counts layer per sample.
    if (length(count_layers) > 1L) assay <- SeuratObject::JoinLayers(assay, layers = "counts")
    counts <- SeuratObject::LayerData(assay, layer = "counts")
    if (!inherits(counts, c("matrix", "Matrix"))) {
        stop("Raw counts must be stored in memory; on-disk count matrices are not supported")
    }
    cells <- colnames(object)
    if (!length(counts) || is.null(colnames(counts)) || is.null(rownames(counts)) ||
        !setequal(colnames(counts), cells)) {
        stop("Assay '", assay_name, "' raw counts are empty or do not match the object's cells")
    }
    counts <- methods::as(Matrix::Matrix(counts[, cells, drop = FALSE], sparse = TRUE),
                          "CsparseMatrix")
    if (anyDuplicated(rownames(counts))) stop("Feature IDs must be unique")
    values <- counts@x
    if (any(!is.finite(values)) || any(values < 0) || any(values != floor(values)) ||
        !any(values > 0)) {
        stop("The counts layer must hold raw nonnegative integer counts, not normalized values")
    }

    source_metadata <- object[[]]
    metadata <- data.frame(row.names = cells)
    for (role in c("sample_id", "donor_id", "condition", "batch")) {
        column <- columns[[role]]
        if (!column %in% names(source_metadata)) {
            stop("Metadata column '", column, "' for ", role, " is not in the object")
        }
        labels <- trimws(as.character(source_metadata[cells, column]))
        if (anyNA(labels) || any(!nzchar(labels))) {
            stop("Metadata column '", column, "' for ", role, " has cells without a value")
        }
        metadata[[role]] <- labels
    }
    # Keep earlier annotations for comparison, clearly separated from new results.
    earlier <- source_metadata[cells, , drop = FALSE]
    names(earlier) <- paste0("input_", names(earlier))
    list(counts = counts, metadata = cbind(metadata, earlier),
         features = data.frame(feature_id = rownames(counts)))
}

cell_qc <- function(counts, mitochondrial_ids, settings) {
    if (!length(mitochondrial_ids) || !all(mitochondrial_ids %in% rownames(counts))) {
        stop("Explicit mitochondrial feature IDs must all occur in the object")
    }
    totals <- Matrix::colSums(counts)
    detected <- Matrix::colSums(counts > 0)
    mito <- 100 * Matrix::colSums(counts[mitochondrial_ids, , drop = FALSE]) / totals
    # Empty cells have undefined mitochondrial percentages and always fail QC.
    keep <- totals > 0 & totals >= settings$min_counts &
        detected >= settings$min_features & detected <= settings$max_features &
        is.finite(mito) & mito <= settings$max_mito_percent
    data.frame(cell_id = colnames(counts), n_counts = totals, n_features = detected,
               mito_percent = mito, retained = keep, row.names = NULL)
}
