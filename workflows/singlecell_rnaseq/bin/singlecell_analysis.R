#!/usr/bin/env Rscript
# Seurat-object analysis adapted conceptually from HBC Intro-to-scRNAseq lessons
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

# 1. Read raw counts and user-confirmed metadata columns. Never infer biology from names.
message("[singlecell:import] ", basename(manifest$input$seurat_rds))
imported <- read_seurat_input("input_object.rds", manifest$input$assay,
                              manifest$input$metadata_columns)
metrics <- cell_qc(imported$counts, unlist(manifest$reference$mitochondrial_gene_ids), manifest$qc)
metrics$sample_id <- imported$metadata$sample_id
sample_ids <- sort(unique(metrics$sample_id))
sample_summary <- data.frame(
    sample_id = sample_ids,
    input_cells = vapply(sample_ids, function(id) sum(metrics$sample_id == id), integer(1)),
    retained_cells = vapply(sample_ids, function(id) sum(metrics$retained[metrics$sample_id == id]),
                            integer(1)))
write_table(metrics, "qc/cell_qc.tsv")
write_table(sample_summary, "qc/sample_qc.tsv")
write_table(imported$features, "tables/features.tsv")
# Refuse to quietly lose a sample. Thresholds must be reviewed deliberately.
too_few <- sample_summary$sample_id[sample_summary$retained_cells < 3L]
if (length(too_few)) stop("Fewer than three retained cells in: ", paste(too_few, collapse = ", "))

# 2. Rebuild from raw counts. Earlier normalization, reductions and clusters are not reused.
message("[singlecell:normalize] LogNormalize; integration=none")
object <- CreateSeuratObject(imported$counts[, metrics$retained, drop = FALSE],
                             project = "MissusTomSingleCell", assay = "RNA",
                             meta.data = imported$metadata[metrics$retained, , drop = FALSE],
                             min.cells = 0, min.features = 0)
object$mito_percent <- metrics$mito_percent[metrics$retained]
rm(imported)
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
writeLines(c("input=existing Seurat object; raw counts reused; input file not modified",
             "recomputed=normalization, variable features, PCA, clusters, UMAP",
             "earlier object metadata is preserved in columns prefixed input_",
             "normalization=LogNormalize; scale.factor=10000; variable.features=vst",
             "integration=none; clustering=Louvain; doublet_detection=not_performed",
             "ambient_rna_correction=not_performed; cell_type_annotation=not_performed",
             "markers=exploratory; condition_differential_expression=not_performed",
             "QC cutoffs are inclusive; mito_percent is 0..100, never a fraction."),
           "tables/provenance/analysis_notes.txt")
message("[singlecell:complete] Review QC, sample mixing, clusters, and exploratory markers.")
