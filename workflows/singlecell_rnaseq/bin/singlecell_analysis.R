#!/usr/bin/env Rscript
# Count-matrix analysis adapted conceptually from HBC Intro-to-scRNAseq lessons
# 03, 05, 07, 10, 11 and 13. Attribution and deliberate changes: START_HERE.md.
# Nextflow orchestrates this script; this script performs the scientific work.
suppressPackageStartupMessages(library(Seurat))
source("import_qc.R")
args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) stop("Expected prepared manifest and CPU count")
manifest <- jsonlite::fromJSON(args[[1]], simplifyVector = FALSE)
analysis <- manifest$analysis
set.seed(analysis$seed)
# Keep execution sequential; BLAS threads are bounded by the Nextflow task.
future::plan("sequential")
for (directory in c("qc", "tables/provenance", "figures", "objects")) {
    dir.create(directory, recursive = TRUE, showWarnings = FALSE)
}
write_table <- function(value, path) {
    write.table(value, path, sep = "\t", quote = TRUE, row.names = FALSE, na = "NA")
}

# 1. Import each confirmed library separately. Never infer biology from filenames.
objects <- list()
qc_rows <- list()
summary_rows <- list()
gene_ids <- NULL
for (sample in manifest$samples) {
    message("[singlecell:import] ", sample$sample_id)
    imported <- read_count_matrix(sample$staged_dir)
    counts <- imported$counts
    if (!is.null(gene_ids) && !identical(gene_ids, rownames(counts))) {
        stop("Samples must share the same ordered feature IDs")
    }
    gene_ids <- rownames(counts)
    metrics <- cell_qc(counts, unlist(manifest$reference$mitochondrial_gene_ids), sample$qc)
    metrics$sample_id <- sample$sample_id
    metrics$cell_id <- paste(sample$sample_id, metrics$barcode, sep = "_")
    qc_rows[[sample$sample_id]] <- metrics
    summary_rows[[sample$sample_id]] <- data.frame(
        sample_id = sample$sample_id, input_cells = ncol(counts), retained_cells = sum(metrics$retained))
    # Refuse to quietly lose a sample. Thresholds must be reviewed deliberately.
    if (sum(metrics$retained) < 3L) stop("Fewer than three retained cells in ", sample$sample_id)
    counts <- counts[, metrics$retained, drop = FALSE]
    colnames(counts) <- metrics$cell_id[metrics$retained]
    object <- CreateSeuratObject(counts, project = sample$sample_id, min.cells = 0, min.features = 0)
    object$sample_id <- sample$sample_id
    object$donor_id <- sample$donor_id
    object$condition <- sample$condition
    object$batch <- sample$batch
    object$mito_percent <- metrics$mito_percent[metrics$retained]
    objects[[sample$sample_id]] <- object
}
write_table(do.call(rbind, qc_rows), "qc/cell_qc.tsv")
write_table(do.call(rbind, summary_rows), "qc/sample_qc.tsv")
write_table(imported$features, "tables/features.tsv")

# 2. Join raw RNA layers for a deliberately unintegrated baseline. Keep raw counts.
message("[singlecell:normalize] LogNormalize; integration=none")
object <- if (length(objects) == 1L) objects[[1]] else merge(objects[[1]], y = objects[-1])
rm(objects, counts, imported)
object <- JoinLayers(object, assay = "RNA")
DefaultAssay(object) <- "RNA"
if (ncol(object) <= analysis$pcs + 2L) stop("Too few retained cells for the requested PCs")
object <- NormalizeData(object, normalization.method = "LogNormalize", scale.factor = 10000)
object <- FindVariableFeatures(object, selection.method = "vst", nfeatures = analysis$variable_features)
if (length(VariableFeatures(object)) <= analysis$pcs) stop("Too few variable genes for the requested PCs")
object <- ScaleData(object, features = VariableFeatures(object))
object <- RunPCA(object, features = VariableFeatures(object), npcs = analysis$pcs,
                 seed.use = analysis$seed)

# 3. Cluster and embed without regressing condition, cell cycle, or mitochondria.
message("[singlecell:cluster] PCA neighbors, Louvain clusters, UMAP")
dimensions <- seq_len(analysis$pcs)
object <- FindNeighbors(object, reduction = "pca", dims = dimensions,
                        k.param = min(20L, ncol(object) - 1L))
object <- FindClusters(object, resolution = analysis$resolution, algorithm = 1,
                       random.seed = analysis$seed)
object <- RunUMAP(object, reduction = "pca", dims = dimensions,
                  n.neighbors = min(30L, ncol(object) - 1L), seed.use = analysis$seed,
                  umap.method = "uwot")
metadata <- object[[]]
metadata$cell_id <- rownames(metadata)
write_table(metadata, "tables/cell_metadata.tsv")
for (group in c("seurat_clusters", "sample_id", "condition", "batch")) {
    plot <- DimPlot(object, reduction = "umap", group.by = group)
    ggplot2::ggsave(paste0("figures/umap_", group, ".pdf"), plot, width = 8, height = 6)
}
ggplot2::ggsave("figures/qc_retained_cells.pdf",
               VlnPlot(object, features = c("nCount_RNA", "nFeature_RNA", "mito_percent"),
                       group.by = "sample_id", pt.size = 0), width = 12, height = 5)
ggplot2::ggsave("figures/pca_elbow.pdf", ElbowPlot(object, ndims = analysis$pcs),
               width = 7, height = 5)

# 4. Markers describe clusters. These are NOT donor-aware condition comparisons.
marker_status <- data.frame(cluster = character(), status = character())
if (isTRUE(analysis$cluster_markers)) {
    message("[singlecell:markers] Exploratory cluster markers on uncorrected RNA")
    clusters <- levels(Idents(object))
    marker_tables <- list()
    for (cluster in clusters) {
        sizes <- table(Idents(object))
        status <- if (length(clusters) < 2L) "skipped_single_cluster" else if (
            sizes[[cluster]] < 3L || sum(sizes) - sizes[[cluster]] < 3L
        ) "skipped_fewer_than_three_cells" else "completed"
        if (status == "completed") {
            markers <- FindMarkers(object, ident.1 = cluster, assay = "RNA", slot = "data",
                                   test.use = "wilcox", only.pos = TRUE,
                                   min.pct = 0.1, logfc.threshold = 0.25, random.seed = analysis$seed)
            if (nrow(markers)) {
                markers$gene_id <- rownames(markers)
                markers$cluster <- cluster
                marker_tables[[cluster]] <- markers
            } else status <- "completed_no_markers"
        }
        marker_status <- rbind(marker_status, data.frame(cluster = cluster, status = status))
    }
    markers <- if (length(marker_tables)) do.call(rbind, marker_tables) else data.frame(
        p_val = numeric(), avg_log2FC = numeric(), pct.1 = numeric(), pct.2 = numeric(),
        p_val_adj = numeric(), gene_id = character(), cluster = character())
    write_table(markers, "tables/exploratory_cluster_markers.tsv")
} else marker_status <- data.frame(cluster = NA_character_, status = "disabled_by_manifest")
write_table(marker_status, "tables/marker_status.tsv")

# 5. Preserve the inspectable object, exact settings, source/input hashes and runtime.
saveRDS(object, "objects/singlecell.rds")
file.copy(args[[1]], "tables/provenance/prepared_manifest.json", overwrite = FALSE)
capture.output(sessionInfo(), file = "tables/provenance/sessionInfo.txt")
capture.output(print(installed.packages()[, c("Package", "Version")], quote = FALSE),
               file = "tables/provenance/installed_packages.txt")
writeLines(c("normalization=LogNormalize; scale.factor=10000; variable.features=vst",
             "integration=none; clustering=Louvain; doublet_detection=not_performed",
             "ambient_rna_correction=not_performed; cell_type_annotation=not_performed",
             "markers=exploratory; condition_differential_expression=not_performed",
             "QC cutoffs are inclusive; mito_percent is 0..100, never a fraction."),
           "tables/provenance/analysis_notes.txt")
message("[singlecell:complete] Review QC, sample mixing, clusters, and exploratory markers.")
