# Sparse import and QC helpers, separate so they can be tested without Seurat.
# Gene IDs stay authoritative; symbols are annotations and may be duplicated.
read_count_matrix <- function(directory) {
    features <- read.delim(gzfile(file.path(directory, "features.tsv.gz")),
                           header = FALSE, stringsAsFactors = FALSE, quote = "",
                           colClasses = "character", check.names = FALSE)
    barcodes <- readLines(gzfile(file.path(directory, "barcodes.tsv.gz")))
    connection <- gzfile(file.path(directory, "matrix.mtx.gz"), "rt")
    on.exit(close(connection), add = TRUE)
    counts <- Matrix::readMM(connection)
    if (!inherits(counts, "sparseMatrix") || ncol(features) != 3L ||
        any(features[[3]] != "Gene Expression") ||
        !identical(dim(counts), c(nrow(features), length(barcodes))) ||
        anyDuplicated(features[[1]]) || anyDuplicated(barcodes) ||
        any(!nzchar(features[[1]])) || any(grepl("[_|[:space:]]", features[[1]]))) {
        stop("Invalid feature/barcode dimensions, identifiers, or modality")
    }
    values <- counts@x
    if (any(!is.finite(values)) || any(values < 0) || any(values != floor(values)) ||
        !any(values > 0)) stop("Counts must be finite nonnegative integers, with some positive counts")
    if (anyDuplicated(paste(counts@i, counts@j, sep = ":"))) {
        stop("Duplicate Matrix Market coordinates are not supported")
    }
    counts <- as(counts, "CsparseMatrix")
    dimnames(counts) <- list(features[[1]], barcodes)
    list(counts = counts, features = data.frame(gene_id = features[[1]],
                                               gene_symbol = features[[2]]))
}

cell_qc <- function(counts, mitochondrial_ids, settings) {
    if (!length(mitochondrial_ids) || !all(mitochondrial_ids %in% rownames(counts))) {
        stop("Explicit mitochondrial feature IDs must all occur in the matrix")
    }
    totals <- Matrix::colSums(counts)
    detected <- Matrix::colSums(counts > 0)
    mito <- 100 * Matrix::colSums(counts[mitochondrial_ids, , drop = FALSE]) / totals
    # Empty cells have undefined mitochondrial percentages and always fail QC.
    keep <- totals > 0 & totals >= settings$min_counts &
        detected >= settings$min_features & detected <= settings$max_features &
        is.finite(mito) & mito <= settings$max_mito_percent
    data.frame(barcode = colnames(counts), n_counts = totals, n_features = detected,
               mito_percent = mito, retained = keep, row.names = NULL)
}
