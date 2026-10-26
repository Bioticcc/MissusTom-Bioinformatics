#!/usr/bin/env Rscript

# =============================================================================
# MISSUS-TOM BULK RNA-SEQ STATISTICAL ANALYSIS
# =============================================================================
#
# PURPOSE
# This script is the final analysis stage of the Bulk RNA-seq workflow. It
# imports Kallisto transcript-abundance tables, combines transcripts into
# genes, runs the existing DESeq2 comparisons, and writes tables and figures.
#
# PIPELINE PLACEMENT
# main.nf runs this after FastQC checks raw and trimmed FASTQ reads, Cutadapt
# trims adapters, and Kallisto quantifies each sample. Its outputs are the
# differential-expression results, quality-control figures, and provenance
# files published by the workflow and displayed by Missus-Tom.
#
# INPUTS AND OUTPUTS
# Inputs are sample metadata, a transcript-to-gene map, comparison definitions,
# numerical thresholds, design settings, custom-figure settings, and Kallisto
# abundance.tsv files. Outputs are tables/, figures/, and
# differential_expression/ directories beneath the supplied output directory.
#
# TERMS
# FASTQ is the standard text format for sequenced reads. A transcript is one
# RNA product of a gene. Normalization accounts for differing sequencing depth.
# A log2 fold change describes the expression ratio between two groups on a
# symmetric scale. An adjusted p-value controls false discoveries when many
# genes are tested. A batch is a technical grouping that can optionally be
# included in the statistical design.
# =============================================================================

# =============================================================================
# SECTION 1: CONSTANTS, PACKAGES, AND COMMAND-LINE INPUT VALIDATION
# =============================================================================
# The workflow calls this script with exactly ten positional arguments. Keep
# their order synchronized with BULK_RNASEQ_ANALYSIS in main.nf.

# Optional gene-class outputs use exact biotype matches only (no pattern grep).
# Accepted lncRNA gene_biotype values are listed in ACCEPTED_LNCRNA_GENE_BIOTYPES
# below and in docs/workflows/bulk_rnaseq/README.md.
PROTEIN_CODING_GENE_BIOTYPE <- "protein_coding"
ACCEPTED_LNCRNA_GENE_BIOTYPES <- c(
  "lncRNA",
  "lincRNA",
  "antisense",
  "sense_intronic",
  "sense_overlapping",
  "bidirectional_promoter_lncrna",
  "macro_lncrna",
  "3prime_overlapping_ncrna"
)

suppressPackageStartupMessages({
  library(DESeq2)
  library(ggplot2)
  library(tximport)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 10) {
  stop(
    "Usage: bulk_rnaseq_analysis.R <samples.tsv> <transcript_to_gene.tsv> <output> ",
    "<comparisons.tsv> <q-value> <absolute-lfc> <minimum-group-size> <experimental-design-type> <adjust-for-batch-effects> <custom-figures.tsv>"
  )
}

sample_sheet_path <- args[[1]]
mapping_path <- args[[2]]
output_root <- args[[3]]
comparison_sheet_path <- args[[4]]
q_value <- as.numeric(args[[5]])
lfc_threshold <- as.numeric(args[[6]])
minimum_group_size <- as.integer(args[[7]])
experimental_design_type <- args[[8]]
adjust_for_batch_effects <- args[[9]]
custom_figures_path <- args[[10]]
if (!is.finite(q_value) || q_value <= 0 || q_value > 1) stop("Adjusted p-value must be in (0, 1]")
if (!is.finite(lfc_threshold) || lfc_threshold < 0) stop("Absolute log2 fold change must be non-negative")
if (is.na(minimum_group_size) || minimum_group_size < 2) stop("Minimum group size must be at least 2")
if (!experimental_design_type %in% c("independent", "paired")) {
  stop("Experimental design type must be independent or paired")
}
if (!adjust_for_batch_effects %in% c("true", "false")) {
  stop("Adjust for batch effects must be true or false")
}
adjust_for_batch_effects <- adjust_for_batch_effects == "true"

# -----------------------------------------------------------------------------
# FUNCTION: Report progress to the workflow log
# PURPOSE: Write a message immediately so the desktop log shows the current
# analysis step. INPUTS: message fragments. OUTPUT: no data value.
# APPENDIX: 1.1
# -----------------------------------------------------------------------------
progress_message <- function(...) {
  message(...)
  flush.console()
}

# Create the stable output layout before any result is written.
# APPENDIX: 1.2
for (directory in c("differential_expression", "figures", "tables")) {
  dir.create(file.path(output_root, directory), recursive = TRUE, showWarnings = FALSE)
}
provenance_dir <- file.path(output_root, "tables", "provenance")
dir.create(provenance_dir, recursive = TRUE, showWarnings = FALSE)

samples <- read.delim(sample_sheet_path, stringsAsFactors = FALSE, check.names = FALSE)
required_columns <- c("sample_id", "condition", "biological_replicate", "batch", "intervention", "abundance_tsv")
if (!all(required_columns %in% colnames(samples))) {
  stop("Sample sheet must contain sample_id, condition, biological_replicate, batch, intervention, and abundance_tsv columns")
}
if (anyDuplicated(samples$sample_id)) stop("Sample identifiers must be unique")
if (!all(file.exists(samples$abundance_tsv))) stop("One or more abundance tables are missing")

comparisons <- read.delim(comparison_sheet_path, stringsAsFactors = FALSE, check.names = FALSE)
custom_figures <- read.delim(custom_figures_path, stringsAsFactors = FALSE, check.names = FALSE)
custom_figure_columns <- c("figure_id", "figure_type", "title", "x_variable", "y_variable", "top_n", "x_axis_mode", "x_axis_minimum", "x_axis_maximum", "y_axis_mode", "y_axis_minimum", "y_axis_maximum")
if (!all(custom_figure_columns %in% colnames(custom_figures))) {
  stop("Custom figure sheet has an unsupported format")
}
# One UTC execution timestamp makes custom artifact names reproducible within a run.
custom_figure_timestamp <- format(Sys.time(), tz = "UTC", format = "%Y-%m-%d_%H-%M-%S")
custom_figure_metadata_rows <- list()
comparison_columns <- c("comparison_id", "numerator", "denominator", "intervention")
if (!all(comparison_columns %in% colnames(comparisons)) || nrow(comparisons) == 0) {
  stop("Comparison sheet must contain comparison_id, numerator, denominator, and intervention rows")
}
if (anyDuplicated(comparisons$comparison_id)) stop("Comparison identifiers must be unique")
known_conditions <- unique(samples$condition)
if (!all(comparisons$numerator %in% known_conditions) || !all(comparisons$denominator %in% known_conditions)) {
  stop("One or more comparisons reference an unknown condition")
}
requested_interventions <- comparisons$intervention[
  !is.na(comparisons$intervention) & nzchar(comparisons$intervention)
]
if (!all(requested_interventions %in% unique(samples$intervention))) {
  stop("One or more comparisons reference an unknown intervention")
}

# =============================================================================
# SECTION 2: INPUT TABLES AND TRANSCRIPT-TO-GENE MAPPING
# =============================================================================

# -----------------------------------------------------------------------------
# FUNCTION: Read and validate the transcript-to-gene map
# PURPOSE: Ensure every transcript identifier maps consistently to one gene
# before tximport combines Kallisto transcript estimates. INPUT: TSV path.
# OUTPUT: validated two-column mapping table. Stops on malformed mappings.
# APPENDIX: 2.1
# -----------------------------------------------------------------------------
read_transcript_to_gene <- function(path) {
  progress_message("Loading transcript-to-gene mapping")
  mapping <- read.delim(path, stringsAsFactors = FALSE, check.names = FALSE)
  required <- c("transcript_id", "gene_id")
  if (!all(required %in% colnames(mapping))) {
    stop("Transcript-to-gene mapping must contain transcript_id and gene_id columns")
  }
  mapping$transcript_id <- trimws(as.character(mapping$transcript_id))
  mapping$gene_id <- trimws(as.character(mapping$gene_id))
  if (any(is.na(mapping$transcript_id) | !nzchar(mapping$transcript_id))) {
    stop("Transcript-to-gene mapping contains an empty transcript_id")
  }
  if (any(is.na(mapping$gene_id) | !nzchar(mapping$gene_id))) {
    stop("Transcript-to-gene mapping contains an empty gene_id")
  }
  if (nrow(mapping) == 0) stop("Transcript-to-gene mapping contains no usable rows")
  mapping <- mapping[order(mapping$transcript_id, mapping$gene_id), , drop = FALSE]
  mapping <- mapping[!duplicated(mapping), , drop = FALSE]

  progress_message("Validating transcript-to-gene mapping")
  transcript_id <- mapping$transcript_id
  gene_id <- mapping$gene_id
  # mapping is already ordered by transcript_id and gene_id above, so one
  # adjacent comparison detects every transcript-to-gene conflict.
  ordered_transcripts <- transcript_id
  ordered_genes <- gene_id
  conflicting_gene_rows <- which(
    ordered_transcripts[-1] == ordered_transcripts[-length(ordered_transcripts)] &
      ordered_genes[-1] != ordered_genes[-length(ordered_genes)]
  )
  if (length(conflicting_gene_rows) > 0) {
    tx <- ordered_transcripts[[conflicting_gene_rows[[1]] + 1]]
    gene_ids <- unique(gene_id[transcript_id == tx])
    stop(
      paste(
        "Transcript",
        tx,
        "maps to multiple gene_id values:",
        paste(gene_ids, collapse = ", ")
      )
    )
  }

  optional_meta <- intersect(c("gene_name", "gene_biotype", "transcript_biotype"), colnames(mapping))
  for (column in optional_meta) {
    values <- ifelse(is.na(mapping[[column]]), "", as.character(mapping[[column]]))
    metadata_order <- order(transcript_id, values)
    ordered_transcripts <- transcript_id[metadata_order]
    ordered_values <- values[metadata_order]
    conflicting_metadata_rows <- which(
      ordered_transcripts[-1] == ordered_transcripts[-length(ordered_transcripts)] &
        ordered_values[-1] != ordered_values[-length(ordered_values)]
    )
    if (length(conflicting_metadata_rows) > 0) {
      tx <- ordered_transcripts[[conflicting_metadata_rows[[1]] + 1]]
      conflicting_values <- unique(values[transcript_id == tx])
      stop(
        paste(
          "Transcript",
          tx,
          "has conflicting",
          column,
          "values:",
          paste(conflicting_values, collapse = ", ")
        )
      )
    }
  }
  mapping <- mapping[!duplicated(mapping$transcript_id), , drop = FALSE]
  mapping <- mapping[order(mapping$transcript_id), , drop = FALSE]
  progress_message(sprintf(
    "Transcript-to-gene mapping complete: %d transcripts / %d genes",
    nrow(mapping),
    length(unique(mapping$gene_id))
  ))
  mapping
}

mapping_table <- read_transcript_to_gene(mapping_path)
tx2gene <- mapping_table[, c("transcript_id", "gene_id")]
colnames(tx2gene) <- c("TXNAME", "GENEID")

gene_cols <- c("gene_id", "gene_name", "gene_biotype")
optional_gene_cols <- intersect(gene_cols, colnames(mapping_table))
gene_annotation <- unique(mapping_table[, optional_gene_cols, drop = FALSE])
gene_annotation <- gene_annotation[!duplicated(gene_annotation$gene_id), , drop = FALSE]
if (!"gene_name" %in% colnames(gene_annotation)) gene_annotation$gene_name <- ""
if (!"gene_biotype" %in% colnames(gene_annotation)) gene_annotation$gene_biotype <- ""
rownames(gene_annotation) <- gene_annotation$gene_id

has_gene_biotype <- "gene_biotype" %in% colnames(mapping_table) &&
  any(nzchar(mapping_table$gene_biotype))

write.table(
  samples[, c("sample_id", "condition", "biological_replicate", "batch", "intervention"), drop = FALSE],
  file.path(provenance_dir, "sample_metadata.tsv"),
  sep = "\t",
  quote = FALSE,
  row.names = FALSE
)
write.table(
  data.frame(
    metric = c(
      "transcript_to_gene_path",
      "mapping_rows",
      "unique_transcripts",
      "unique_genes",
      "has_gene_name",
      "has_gene_biotype",
      "has_transcript_biotype"
    ),
    value = c(
      mapping_path,
      nrow(mapping_table),
      length(unique(mapping_table$transcript_id)),
      length(unique(mapping_table$gene_id)),
      "gene_name" %in% colnames(mapping_table),
      has_gene_biotype,
      "transcript_biotype" %in% colnames(mapping_table)
    ),
    stringsAsFactors = FALSE
  ),
  file.path(provenance_dir, "reference_mapping_summary.tsv"),
  sep = "\t",
  quote = FALSE,
  row.names = FALSE
)
write.table(
  data.frame(
    parameter = c(
      "adjusted_p_value",
      "absolute_log2_fold_change",
      "minimum_group_size",
      "experimental_design_type",
      "adjust_for_batch_effects",
      "design_formula",
      "log2_fold_change_numerator",
      "log2_fold_change_denominator"
    ),
    value = c(
      q_value,
      lfc_threshold,
      minimum_group_size,
      experimental_design_type,
      adjust_for_batch_effects,
      paste("~", paste(c(
        if (adjust_for_batch_effects) "batch",
        if (experimental_design_type == "paired") "biological_replicate",
        "condition"
      ), collapse = " + ")),
      "manifest comparison numerator (case)",
      "manifest comparison denominator (reference)"
    ),
    stringsAsFactors = FALSE
  ),
  file.path(provenance_dir, "analysis_parameters.tsv"),
  sep = "\t",
  quote = FALSE,
  row.names = FALSE
)

quant_files <- samples$abundance_tsv
# APPENDIX: 2.2
names(quant_files) <- samples$sample_id
progress_message("Importing Kallisto abundance tables")
txi <- tximport(
  quant_files,
  type = "kallisto",
  tx2gene = tx2gene,
  ignoreAfterBar = TRUE,
  dropInfReps = TRUE,
  countsFromAbundance = "no"
)

# =============================================================================
# SECTION 3: PLOTTING AND HUMAN-READABLE REPORT HELPERS
# =============================================================================

# Save one ggplot in the existing PDF and PNG formats. Inputs are the plot,
# filename stem, and dimensions; the two image files are its side effects.
# APPENDIX: 3.1
save_ggplot <- function(plot, stem, width = 8, height = 6) {
  ggsave(paste0(stem, ".png"), plot, width = width, height = height, dpi = 160)
  ggsave(paste0(stem, ".pdf"), plot, width = width, height = height)
}

# Draw an expression heatmap with sample-group annotation. The matrix contains
# genes by samples; this writes the requested image without changing its data.
# APPENDIX: 3.2
plot_heatmap <- function(matrix, annotation_groups, case_group, filename, title, width = 1100, height = 900) {
  colors <- colorRampPalette(c("#173331", "#f7faf8", "#a23b3b"))(100)
  png(filename, width = width, height = height, res = 130)
  tryCatch({
    heatmap(
      matrix,
      scale = "row",
      col = colors,
      margins = c(9, 8),
      labRow = NA,
      main = title,
      ColSideColors = ifelse(annotation_groups == case_group, "#a15d14", "#1e655d")
    )
  }, finally = dev.off())
}

# Escape text before it is inserted into the self-contained PCA HTML report.
# APPENDIX: 3.3
html_escape <- function(value) {
  value <- gsub("&", "&amp;", value, fixed = TRUE)
  value <- gsub("<", "&lt;", value, fixed = TRUE)
  value <- gsub(">", "&gt;", value, fixed = TRUE)
  value
}

# Write the interactive-free HTML PCA summary from already calculated PCA data.
# PCA (principal component analysis) summarizes major expression variation.
# APPENDIX: 3.4
write_pca_html <- function(pca_df, percent_var, filename, title, case_group) {
  if (!all(c("PC1", "PC2", "PC3") %in% colnames(pca_df))) {
    stop("3D PCA HTML requires PC1, PC2, and PC3 columns")
  }
  # Map a numerical PCA coordinate into the fixed SVG drawing area.
  project <- function(values, low, high) {
    span <- diff(range(values))
    if (!is.finite(span) || span == 0) return(rep((low + high) / 2, length(values)))
    low + (values - min(values)) / span * (high - low)
  }
  px <- project(pca_df$PC1 - 0.45 * pca_df$PC3, 75, 825)
  py <- project(pca_df$PC2 + 0.35 * pca_df$PC3, 525, 75)
  colors <- ifelse(pca_df$condition == case_group, "#a15d14", "#1e655d")
  points <- paste0(
    '<g><circle cx="', round(px, 1), '" cy="', round(py, 1), '" r="7" fill="', colors,
    '"><title>', html_escape(pca_df$sample_id), " · ", html_escape(pca_df$condition),
    "</title></circle><text x=\"", round(px + 10, 1), '" y="', round(py + 4, 1),
    '" font-size="12">', html_escape(pca_df$sample_id), "</text></g>", collapse = "\n"
  )
  html <- paste0(
    "<!doctype html><html><head><meta charset=\"utf-8\"><title>", html_escape(title),
    "</title><style>body{font:14px system-ui;color:#173331;margin:24px}svg{max-width:100%;height:auto;border:1px solid #dce5e1;background:#fff}</style></head><body><h1>",
    html_escape(title), "</h1><p>Projected PC1, PC2, and PC3. Hover over a point for sample metadata.</p>",
    '<svg viewBox="0 0 900 600" role="img"><line x1="55" y1="545" x2="850" y2="545" stroke="#617370"/><line x1="55" y1="545" x2="55" y2="45" stroke="#617370"/>',
    points,
    '<text x="370" y="585">PC1 (', percent_var[[1]], '%)</text><text x="10" y="300" transform="rotate(-90 10 300)">PC2 (', percent_var[[2]], '%); PC3 (', percent_var[[3]], '%) projected</text></svg></body></html>'
  )
  writeLines(html, filename, useBytes = TRUE)
}

# Record why a requested analysis class was skipped, preserving provenance.
# APPENDIX: 3.5
write_skip_rationale <- function(output_root, analysis_name, comparison_id, rationale) {
  table_dir <- file.path(output_root, "tables", analysis_name, comparison_id)
  dir.create(table_dir, recursive = TRUE, showWarnings = FALSE)
  writeLines(rationale, file.path(table_dir, "skip_rationale.txt"), useBytes = TRUE)
}

# =============================================================================
# SECTION 4: OUTPUT PROVENANCE AND OPTIONAL GENE CLASSES
# =============================================================================

# Build the existing all-gene and, when annotated, biotype-specific analysis
# classes. Inputs are gene results and annotations; output is named gene sets.
# APPENDIX: 4.1
build_analysis_classes <- function(all_genes, gene_annotation, has_gene_biotype) {
  classes <- list(all_genes = all_genes)
  skips <- list()
  if (!has_gene_biotype) {
    skips$mRNA <- "gene_biotype column is absent from transcript_to_gene mapping"
    skips$lncRNA <- "gene_biotype column is absent from transcript_to_gene mapping"
    return(list(classes = classes, skips = skips))
  }
  mrna_genes <- intersect(
    all_genes,
    gene_annotation$gene_id[gene_annotation$gene_biotype == PROTEIN_CODING_GENE_BIOTYPE]
  )
  if (length(mrna_genes) >= 2) {
    classes$mRNA <- mrna_genes
  } else {
    skips$mRNA <- paste0(
      "Fewer than two protein_coding genes matched (found ", length(mrna_genes), ")"
    )
  }
  lnc_genes <- intersect(
    all_genes,
    gene_annotation$gene_id[gene_annotation$gene_biotype %in% ACCEPTED_LNCRNA_GENE_BIOTYPES]
  )
  if (length(lnc_genes) >= 2) {
    classes$lncRNA <- lnc_genes
  } else {
    skips$lncRNA <- paste0(
      "Fewer than two genes with accepted lncRNA biotypes matched (found ", length(lnc_genes), ")"
    )
  }
  list(classes = classes, skips = skips)
}

all_statuses <- list()
status_index <- 0
optional_skip_log <- list()
optional_de_generated <- c(mRNA = FALSE, lncRNA = FALSE)
output_contract_rows <- list()

# Convert an internal class key into the existing reader-facing label.
# APPENDIX: 4.2
analysis_class_label <- function(analysis_name) {
  if (analysis_name == "all_genes") "all-gene" else analysis_name
}

# Check whether an expected output exists and is not an empty file.
# APPENDIX: 4.3
artifact_path_nonempty <- function(path) {
  isTRUE(file.exists(path)) && isTRUE(file.info(path)$size > 0)
}

# Store output paths relative to the result root for portable provenance tables.
# APPENDIX: 4.4
relative_output_path <- function(path) {
  root <- normalizePath(output_root, winslash = "/", mustWork = FALSE)
  normalized <- normalizePath(path, winslash = "/", mustWork = FALSE)
  pattern <- paste0("^", gsub("([.|()[\\^{}+$*?]|])", "\\\\\\1", root), "/?")
  sub(pattern, "", normalized)
}

# Add one artifact row to the in-memory output contract used at export time.
# APPENDIX: 4.5
record_output_contract <- function(
  comparison_id,
  analysis_class,
  artifact,
  status,
  relative_path = "",
  rationale = ""
) {
  output_contract_rows <<- c(
    output_contract_rows,
    list(
      data.frame(
        comparison_id = comparison_id,
        analysis_class = analysis_class,
        artifact = artifact,
        status = status,
        relative_path = relative_path,
        rationale = rationale,
        stringsAsFactors = FALSE
      )
    )
  )
}

# Record a generated file only when it is present and non-empty.
# APPENDIX: 4.6
record_artifact_file <- function(comparison_id, analysis_class, artifact, abs_path, rationale = "") {
  rel <- relative_output_path(abs_path)
  if (artifact_path_nonempty(abs_path)) {
    record_output_contract(comparison_id, analysis_class, artifact, "generated", rel, rationale)
  } else {
    record_output_contract(
      comparison_id,
      analysis_class,
      artifact,
      "failed",
      rel,
      if (nzchar(rationale)) rationale else "Expected output file missing or empty"
    )
  }
}

# Record an intentionally skipped artifact with an explanation for the user.
# APPENDIX: 4.7
record_artifact_skipped <- function(comparison_id, analysis_class, artifact, rationale) {
  record_output_contract(comparison_id, analysis_class, artifact, "skipped", "", rationale)
}

# =============================================================================
# SECTION 5: OPTIONAL CUSTOM-FIGURE HELPERS
# =============================================================================

# Make a safe, unique existing filename stem from the requested title and ID.
# APPENDIX: 5.1
safe_figure_filename <- function(title, figure_id, prior_stems) {
  stem <- gsub("[^A-Za-z0-9._-]+", "_", trimws(title))
  stem <- gsub("_+", "_", stem)
  stem <- gsub("^[._-]+|[._-]+$", "", stem)
  if (!nzchar(stem)) stem <- "Custom_Figure"
  stem <- paste0(stem, "_", custom_figure_timestamp)
  if (stem %in% prior_stems) stem <- paste0(stem, "_", figure_id)
  stem
}

# Apply only the already validated optional manual axis limits to a ggplot.
# APPENDIX: 5.2
apply_custom_axes <- function(plot, spec) {
  # Read an optional numeric axis bound while preserving invalid values as NA.
  numeric_value <- function(column) suppressWarnings(as.numeric(spec[[column]][[1]]))
  x_min <- numeric_value("x_axis_minimum"); x_max <- numeric_value("x_axis_maximum")
  y_min <- numeric_value("y_axis_minimum"); y_max <- numeric_value("y_axis_maximum")
  x_limits <- if (spec$x_axis_mode[[1]] == "manual" && is.finite(x_min) && is.finite(x_max) && x_min < x_max) c(x_min, x_max) else NULL
  y_limits <- if (spec$y_axis_mode[[1]] == "manual" && is.finite(y_min) && is.finite(y_max) && y_min < y_max) c(y_min, y_max) else NULL
  if (!is.null(x_limits) || !is.null(y_limits)) plot <- plot + coord_cartesian(xlim = x_limits, ylim = y_limits)
  plot
}

# Select the requested existing DESeq2 result metric for a custom scatterplot.
# APPENDIX: 5.3
metric_values <- function(result_df, variable) {
  source <- switch(variable,
    base_mean = result_df$baseMean,
    log2_fold_change = result_df$log2FoldChange,
    p_value = result_df$pvalue,
    adjusted_p_value = result_df$padj,
    minus_log10_p_value = -log10(pmax(result_df$pvalue, .Machine$double.xmin)),
    minus_log10_adjusted_p_value = -log10(pmax(result_df$padj, .Machine$double.xmin)),
    stat = result_df$stat,
    lfc_standard_error = result_df$lfcSE,
    NULL
  )
  if (is.null(source)) return(NULL)
  as.numeric(source)
}

# Generate configured figures from existing analysis objects. It writes files
# and metadata; it does not change any DESeq2 calculation or default figure.
# APPENDIX: 5.4
generate_custom_figures <- function(comparison_id, class_label, result_df, rlog_matrix, normalized_counts, selected_samples, significant) {
  if (nrow(custom_figures) == 0) return(invisible(NULL))
  custom_root <- file.path(output_root, "figures", "custom", comparison_id)
  dir.create(custom_root, recursive = TRUE, showWarnings = FALSE)
  used_stems <- character()
  for (row_index in seq_len(nrow(custom_figures))) {
    spec <- custom_figures[row_index, , drop = FALSE]
    figure_id <- as.character(spec$figure_id[[1]])
    figure_type <- as.character(spec$figure_type[[1]])
    title <- as.character(spec$title[[1]])
    filename_stem <- safe_figure_filename(title, figure_id, used_stems)
    used_stems <- c(used_stems, filename_stem)
    stem <- file.path(custom_root, filename_stem)
    artifact <- paste("custom figure", figure_id)
    tryCatch({
      if (figure_type == "gene_metric_scatter") {
        x <- metric_values(result_df, as.character(spec$x_variable[[1]])); y <- metric_values(result_df, as.character(spec$y_variable[[1]]))
        values <- data.frame(x = x, y = y); values <- values[is.finite(values$x) & is.finite(values$y), , drop = FALSE]
        if (nrow(values) < 2) stop("fewer than two finite gene values")
        plot <- ggplot(values, aes(x, y)) + geom_point(alpha = 0.55, size = 1) + labs(title = title, x = spec$x_variable[[1]], y = spec$y_variable[[1]]) + theme_bw(base_size = 12)
      } else if (figure_type == "sample_correlation_heatmap") {
        correlation <- cor(rlog_matrix, use = "pairwise.complete.obs")
        if (ncol(correlation) < 2) stop("fewer than two samples")
        png(paste0(stem, ".png"), width = 1000, height = 900, res = 130); heatmap(correlation, symm = TRUE, col = colorRampPalette(c("#ffffff", "#1e655d"))(100), margins = c(9, 9), main = title); dev.off()
        pdf(paste0(stem, ".pdf"), width = 8, height = 7); heatmap(correlation, symm = TRUE, col = colorRampPalette(c("#ffffff", "#1e655d"))(100), margins = c(9, 9), main = title); dev.off()
        record_artifact_file(comparison_id, class_label, artifact, paste0(stem, ".png"), "rlog sample correlation")
        record_artifact_file(comparison_id, class_label, paste(artifact, "PDF"), paste0(stem, ".pdf"), "rlog sample correlation")
        custom_figure_metadata_rows <<- c(custom_figure_metadata_rows, list(data.frame(figure_id, figure_type, title, filename = basename(stem), timestamp_utc = custom_figure_timestamp, x_variable = spec$x_variable[[1]], y_variable = spec$y_variable[[1]], x_axis_mode = spec$x_axis_mode[[1]], y_axis_mode = spec$y_axis_mode[[1]], status = "generated", reason = "", stringsAsFactors = FALSE)))
        next
      } else if (figure_type == "expression_distribution_boxplot") {
        grouping <- if (as.character(spec$x_variable[[1]]) == "condition") selected_samples$condition else colnames(rlog_matrix)
        values <- data.frame(group = rep(grouping, each = nrow(rlog_matrix)), expression = as.vector(rlog_matrix))
        plot <- ggplot(values, aes(group, expression, fill = group)) + geom_boxplot(outlier.size = 0.5) + labs(title = title, x = ifelse(spec$x_variable[[1]] == "condition", "Experimental condition", "Sample ID"), y = "rlog normalized gene expression") + theme_bw(base_size = 12) + theme(legend.position = "none", axis.text.x = element_text(angle = 45, hjust = 1))
      } else if (figure_type == "top_de_genes_bar") {
        top_n <- as.integer(spec$top_n[[1]]); values <- significant[order(abs(significant$log2FoldChange), decreasing = TRUE), , drop = FALSE]; values <- head(values, top_n)
        if (nrow(values) == 0) stop("no qualifying genes")
        values$label <- ifelse(is.na(values$gene_name) | !nzchar(values$gene_name), values$gene_id, values$gene_name)
        plot <- ggplot(values, aes(reorder(label, log2FoldChange), log2FoldChange, fill = log2FoldChange > 0)) + geom_col() + coord_flip() + labs(title = title, x = "Gene", y = "Log2 fold change (numerator vs denominator)") + theme_bw(base_size = 12) + theme(legend.position = "none")
      } else if (figure_type == "estimated_gene_count_bar") {
        values <- data.frame(sample_id = colnames(normalized_counts), estimated_gene_counts = colSums(normalized_counts, na.rm = TRUE))
        plot <- ggplot(values, aes(sample_id, estimated_gene_counts)) + geom_col(fill = "#1e655d") + labs(title = title, x = "Sample ID", y = "Sum of estimated gene counts") + theme_bw(base_size = 12) + theme(axis.text.x = element_text(angle = 45, hjust = 1))
      } else stop("unsupported figure type")
      plot <- apply_custom_axes(plot, spec)
      save_ggplot(plot, stem, 8, 6)
      record_artifact_file(comparison_id, class_label, artifact, paste0(stem, ".png"), paste("type", figure_type))
      record_artifact_file(comparison_id, class_label, paste(artifact, "PDF"), paste0(stem, ".pdf"), paste("type", figure_type))
      custom_figure_metadata_rows <<- c(custom_figure_metadata_rows, list(data.frame(figure_id, figure_type, title, filename = basename(stem), timestamp_utc = custom_figure_timestamp, x_variable = spec$x_variable[[1]], y_variable = spec$y_variable[[1]], x_axis_mode = spec$x_axis_mode[[1]], y_axis_mode = spec$y_axis_mode[[1]], status = "generated", reason = "", stringsAsFactors = FALSE)))
    }, error = function(error) {
      record_artifact_skipped(comparison_id, class_label, artifact, conditionMessage(error))
      custom_figure_metadata_rows <<- c(custom_figure_metadata_rows, list(data.frame(figure_id, figure_type, title, filename = "", timestamp_utc = custom_figure_timestamp, x_variable = spec$x_variable[[1]], y_variable = spec$y_variable[[1]], x_axis_mode = spec$x_axis_mode[[1]], y_axis_mode = spec$y_axis_mode[[1]], status = "skipped", reason = conditionMessage(error), stringsAsFactors = FALSE)))
      progress_message(sprintf("Skipped %s: %s", artifact, conditionMessage(error)))
    })
  }
}

analysis_artifacts <- c(
  "differential expression full results",
  "differential expression significant genes",
  "differential expression upregulated genes",
  "differential expression downregulated genes",
  "library-size normalized matrix",
  "rlog normalized matrix",
  "2D PCA plot",
  "scree plot",
  "3D PCA plot",
  "3D PCA HTML",
  "top-gene heatmap",
  "volcano plot",
  "MA plot",
  "p-value histogram",
  "adjusted p-value histogram",
  "fold-change density",
  "sample-distance heatmap",
  "DE counts by comparison plot",
  "DE totals by comparison plot",
  "comparison status table"
)

# Record every standard artifact as skipped for an unavailable gene class.
# APPENDIX: 5.5
record_class_skipped <- function(comparison_id, analysis_class, rationale) {
  for (artifact in analysis_artifacts) {
    record_artifact_skipped(comparison_id, analysis_class, artifact, rationale)
  }
}

# =============================================================================
# SECTION 6: DESEQ2 FITTING AND COMPARISON ANALYSIS
# =============================================================================

# Fit the existing DESeq2 model, using gene-wise dispersions only for very
# small valid gene sets where the standard dispersion trend cannot be fitted.
# APPENDIX: 6.1
run_deseq_robust <- function(dds) {
  tryCatch(
    DESeq(dds, quiet = TRUE),
    error = function(error) {
      message_text <- conditionMessage(error)
      if (!grepl("standard curve fitting techniques will not work", message_text, fixed = TRUE)) {
        stop(error)
      }
      # Very small valid gene sets cannot support a fitted dispersion trend.
      # DESeq2 explicitly recommends using their gene-wise estimates in this case.
      dds <- estimateSizeFactors(dds)
      dds <- estimateDispersionsGeneEst(dds, quiet = TRUE)
      dispersions(dds) <- mcols(dds)$dispGeneEst
      mcols(dds)$dispFit <- mcols(dds)$dispGeneEst
      nbinomWaldTest(dds, quiet = TRUE)
    }
  )
}

# Each comparison is analyzed independently so its requested numerator,
# denominator, optional intervention, and output directory remain traceable.
# APPENDIX: 6.2
for (comparison_index in seq_len(nrow(comparisons))) {
  comparison_id <- comparisons$comparison_id[[comparison_index]]
  progress_message(sprintf("Preparing comparison %s", comparison_id))
  case_group <- comparisons$numerator[[comparison_index]]
  reference_group <- comparisons$denominator[[comparison_index]]
  intervention_filter <- comparisons$intervention[[comparison_index]]
  if (is.na(intervention_filter)) intervention_filter <- ""
  comparison_label <- paste(
    case_group,
    "vs",
    reference_group,
    if (nzchar(intervention_filter)) paste("within", intervention_filter) else ""
  )
  # Select only the samples represented by this comparison before building the
  # DESeq2 design. An intervention filter narrows the same comparison further.
  selected_samples <- samples[samples$condition %in% c(reference_group, case_group), , drop = FALSE]
  if (nzchar(intervention_filter)) {
    selected_samples <- selected_samples[
      !is.na(selected_samples$intervention) & selected_samples$intervention == intervention_filter,
      ,
      drop = FALSE
    ]
  }
  condition_counts <- table(selected_samples$condition)
  if (any(condition_counts[c(reference_group, case_group)] < minimum_group_size)) {
    stop(paste("Comparison", comparison_id, "does not meet the minimum group size"))
  }
  if (experimental_design_type == "paired") {
    if (any(is.na(selected_samples$biological_replicate) | !nzchar(selected_samples$biological_replicate))) {
      stop(paste("Comparison", comparison_id, "has samples without biological replicate IDs"))
    }
    assignment_counts <- table(selected_samples$biological_replicate, selected_samples$condition)
    if (any(assignment_counts > 1) || any(rowSums(assignment_counts > 0) != 2) ||
        any(assignment_counts[, c(reference_group, case_group), drop = FALSE] != 1)) {
      stop(paste("Comparison", comparison_id, "does not contain exactly one matched sample per subject and condition"))
    }
    if (nrow(assignment_counts) < minimum_group_size) {
      stop(paste("Comparison", comparison_id, "does not meet the minimum paired-subject count"))
    }
  }
  if (adjust_for_batch_effects) {
    if (any(is.na(selected_samples$batch) | !nzchar(selected_samples$batch))) {
      stop(paste("Comparison", comparison_id, "has samples without batch assignments"))
    }
    if (length(unique(selected_samples$batch)) < 2) {
      stop(paste("Comparison", comparison_id, "requires at least two batches for adjustment"))
    }
  }
  comparison_txi <- lapply(txi, function(value) {
    if (is.matrix(value) && ncol(value) == nrow(samples)) {
      value[, selected_samples$sample_id, drop = FALSE]
    } else {
      value
    }
  })
  col_data <- data.frame(
    condition = factor(selected_samples$condition, levels = c(reference_group, case_group)),
    row.names = selected_samples$sample_id
  )
  if (experimental_design_type == "paired") {
    col_data$biological_replicate <- factor(selected_samples$biological_replicate)
  }
  if (adjust_for_batch_effects) col_data$batch <- factor(selected_samples$batch)
  # The formula tells DESeq2 which variation is condition of interest and
  # whether paired subjects and/or technical batches are existing covariates.
  design_formula <- as.formula(paste(
    "~",
    paste(c(
      if (adjust_for_batch_effects) "batch",
      if (experimental_design_type == "paired") "biological_replicate",
      "condition"
    ), collapse = " + ")
  ))
  if (adjust_for_batch_effects) {
    design_matrix <- model.matrix(design_formula, data = col_data)
    if (nrow(design_matrix) <= ncol(design_matrix) || qr(design_matrix)$rank != ncol(design_matrix)) {
      stop(paste(
        "Comparison", comparison_id,
        "has a confounded batch, subject, and condition model or no residual degrees of freedom"
      ))
    }
  }
  # Positive log2 fold change corresponds to the manifest numerator (case) vs denominator (reference).
  contrast <- c("condition", case_group, reference_group)

  class_plan <- build_analysis_classes(rownames(comparison_txi$counts), gene_annotation, has_gene_biotype)
  analysis_classes <- class_plan$classes
  for (optional_name in names(class_plan$skips)) {
    write_skip_rationale(output_root, optional_name, comparison_id, class_plan$skips[[optional_name]])
    optional_skip_log[[length(optional_skip_log) + 1]] <- data.frame(
      comparison_id = comparison_id,
      analysis = optional_name,
      status = "skipped",
      rationale = class_plan$skips[[optional_name]],
      stringsAsFactors = FALSE
    )
    record_class_skipped(comparison_id, optional_name, class_plan$skips[[optional_name]])
  }

  analysis_results <- list()

  # Run the unchanged analysis once for all genes and, where annotation permits,
  # once for each optional biological gene class.
  for (analysis_name in names(analysis_classes)) {
    class_label <- analysis_class_label(analysis_name)
    selected_genes <- intersect(rownames(comparison_txi$counts), analysis_classes[[analysis_name]])
    if (length(selected_genes) < 2) {
      if (analysis_name == "all_genes") {
        stop(paste("Insufficient genes for all-gene analysis in comparison", comparison_id))
      }
      write_skip_rationale(
        output_root,
        analysis_name,
        comparison_id,
        paste("Fewer than two genes available after filtering (found", length(selected_genes), ")")
      )
      record_class_skipped(
        comparison_id,
        class_label,
        paste("Fewer than two genes available after filtering (found", length(selected_genes), ")")
      )
      next
    }

    class_txi <- lapply(comparison_txi, function(value) {
      if (is.matrix(value) && nrow(value) == nrow(comparison_txi$counts)) {
        value[selected_genes, , drop = FALSE]
      } else {
        value
      }
    })
    de_dir <- file.path(output_root, "differential_expression", analysis_name, comparison_id)
    figure_dir <- file.path(output_root, "figures", analysis_name, comparison_id)
    table_dir <- file.path(output_root, "tables", analysis_name, comparison_id)
    dir.create(de_dir, recursive = TRUE, showWarnings = FALSE)
    dir.create(figure_dir, recursive = TRUE, showWarnings = FALSE)
    dir.create(table_dir, recursive = TRUE, showWarnings = FALSE)

    dds <- DESeqDataSetFromTximport(class_txi, colData = col_data, design = design_formula)
    # Retain genes with sufficient observed counts in at least the smaller
    # condition group; this existing filter avoids testing uninformative genes.
    keep <- rowSums(counts(dds) >= 10) >= min(condition_counts[c(reference_group, case_group)])
    dds <- dds[keep, ]
    if (nrow(dds) < 2) {
      if (analysis_name == "all_genes") {
        stop(paste("Insufficient expressed genes after filtering for comparison", comparison_id))
      }
      write_skip_rationale(
        output_root,
        analysis_name,
        comparison_id,
        paste("Fewer than two genes passed expression filtering (found", nrow(dds), ")")
      )
      record_class_skipped(
        comparison_id,
        class_label,
        paste("Fewer than two genes passed expression filtering (found", nrow(dds), ")")
      )
      next
    }
    progress_label <- switch(
      analysis_name,
      all_genes = "all genes",
      mRNA = "mRNA",
      lncRNA = "lncRNA",
      analysis_name
    )
    progress_message(sprintf("Running DESeq2 for %s (%s)", progress_label, comparison_id))
    dds <- run_deseq_robust(dds)
    # DESeq2 tests the requested condition contrast. Shrinkage stabilizes noisy
    # effect-size estimates while retaining the existing statistical method.
    raw_result <- results(dds, contrast = contrast, alpha = q_value)
    result <- lfcShrink(dds, contrast = contrast, res = raw_result, type = "normal")
    result_df <- as.data.frame(result)
    result_df$gene_id <- rownames(result_df)
    result_df$gene_name <- gene_annotation[result_df$gene_id, "gene_name"]
    result_df$gene_biotype <- gene_annotation[result_df$gene_id, "gene_biotype"]
    result_df <- result_df[, c(
      "gene_id", "gene_name", "gene_biotype", "baseMean", "log2FoldChange",
      "lfcSE", "stat", "pvalue", "padj"
    )]
    result_df <- result_df[order(result_df$padj, result_df$pvalue, na.last = TRUE), ]
    # A significant gene meets both the adjusted-p-value and absolute-effect
    # thresholds supplied by the project manifest.
    significant <- result_df[
      !is.na(result_df$padj) & result_df$padj < q_value & abs(result_df$log2FoldChange) > lfc_threshold,
    ]
    up <- significant[significant$log2FoldChange > lfc_threshold, ]
    down <- significant[significant$log2FoldChange < -lfc_threshold, ]
    threshold_suffix <- paste0(
      "padj", format(q_value, trim = TRUE, scientific = FALSE),
      "_lfc", format(lfc_threshold, trim = TRUE, scientific = FALSE)
    )

    progress_message(sprintf("Writing figures and tables for %s (%s)", progress_label, comparison_id))
    write.table(result_df, file.path(de_dir, "full_results.tsv"), sep = "\t", quote = FALSE, row.names = FALSE)
    write.table(
      significant,
      file.path(de_dir, paste0("significant_", threshold_suffix, ".tsv")),
      sep = "\t",
      quote = FALSE,
      row.names = FALSE
    )
    write.table(
      up,
      file.path(de_dir, paste0("upregulated_", threshold_suffix, ".tsv")),
      sep = "\t",
      quote = FALSE,
      row.names = FALSE
    )
    write.table(
      down,
      file.path(de_dir, paste0("downregulated_", threshold_suffix, ".tsv")),
      sep = "\t",
      quote = FALSE,
      row.names = FALSE
    )
    record_artifact_file(
      comparison_id,
      class_label,
      "differential expression full results",
      file.path(de_dir, "full_results.tsv")
    )
    record_artifact_file(
      comparison_id,
      class_label,
      "differential expression significant genes",
      file.path(de_dir, paste0("significant_", threshold_suffix, ".tsv"))
    )
    record_artifact_file(
      comparison_id,
      class_label,
      "differential expression upregulated genes",
      file.path(de_dir, paste0("upregulated_", threshold_suffix, ".tsv"))
    )
    record_artifact_file(
      comparison_id,
      class_label,
      "differential expression downregulated genes",
      file.path(de_dir, paste0("downregulated_", threshold_suffix, ".tsv"))
    )
    write.table(
      as.data.frame(counts(dds, normalized = TRUE)),
      file.path(table_dir, "library_size_normalized_counts.tsv"),
      sep = "\t",
      quote = FALSE,
      col.names = NA
    )

    progress_message(sprintf("Computing rlog/PCA for %s (%s)", progress_label, comparison_id))
    # rlog transforms normalized counts for visualization; it is not used to
    # replace the count-based DESeq2 test above.
    rld <- rlog(dds, blind = FALSE, fitType = "mean")
    rlog_matrix <- assay(rld)
    write.table(
      as.data.frame(rlog_matrix),
      file.path(table_dir, "rlog_normalized_expression.tsv"),
      sep = "\t",
      quote = FALSE,
      col.names = NA
    )
    record_artifact_file(
      comparison_id,
      class_label,
      "library-size normalized matrix",
      file.path(table_dir, "library_size_normalized_counts.tsv")
    )
    record_artifact_file(
      comparison_id,
      class_label,
      "rlog normalized matrix",
      file.path(table_dir, "rlog_normalized_expression.tsv")
    )

    # PCA summarizes the strongest sample-to-sample expression patterns.
    pca <- prcomp(t(rlog_matrix), scale. = FALSE)
    variance <- 100 * pca$sdev^2 / sum(pca$sdev^2)
    n_pc <- ncol(pca$x)
    pca_df <- data.frame(
      sample_id = rownames(pca$x),
      condition = col_data[rownames(pca$x), "condition"],
      stringsAsFactors = FALSE
    )
    if (n_pc >= 1) pca_df$PC1 <- pca$x[, 1]
    if (n_pc >= 2) pca_df$PC2 <- pca$x[, 2]
    if (n_pc >= 3) pca_df$PC3 <- pca$x[, 3]

    if (n_pc >= 2) {
      pca_plot <- ggplot(pca_df, aes(PC1, PC2, color = condition, label = sample_id)) +
        geom_point(size = 4) +
        geom_text(hjust = 1.08, vjust = -0.55, size = 3, show.legend = FALSE) +
        scale_color_manual(values = setNames(c("#1e655d", "#a15d14"), c(reference_group, case_group))) +
        scale_x_continuous(expand = expansion(mult = c(0.20, 0.12))) +
        labs(
          title = paste("2D PCA -", analysis_name, comparison_label),
          x = sprintf("PC1: %.1f%% variance", variance[[1]]),
          y = sprintf("PC2: %.1f%% variance", variance[[2]])
        ) +
        theme_bw(base_size = 12) +
        theme(legend.position = "bottom")
      save_ggplot(pca_plot, file.path(figure_dir, "2D_PCA_plot"), 9, 6)
      record_artifact_file(
        comparison_id,
        class_label,
        "2D PCA plot",
        file.path(figure_dir, "2D_PCA_plot.png")
      )
    } else {
      record_artifact_skipped(
        comparison_id,
        class_label,
        "2D PCA plot",
        paste("Fewer than two principal components available (found", n_pc, ")")
      )
    }

    scree_df <- data.frame(
      component = factor(paste0("PC", seq_along(variance)), levels = paste0("PC", seq_along(variance))),
      variance = variance
    )
    scree_plot <- ggplot(scree_df, aes(component, variance)) +
      geom_col(fill = "#1e655d") +
      labs(title = "Scree plot", x = "Principal component", y = "Variance explained (%)") +
      theme_minimal(base_size = 12) +
      theme(axis.text.x = element_text(angle = 60, hjust = 1))
    scree_path <- file.path(figure_dir, "Scree_plot.png")
    ggsave(scree_path, scree_plot, width = 8, height = 5, dpi = 160)
    record_artifact_file(comparison_id, class_label, "scree plot", scree_path)

    if (n_pc >= 3) {
      projected <- transform(pca_df, projected_x = PC1 - 0.45 * PC3, projected_y = PC2 + 0.35 * PC3)
      pca_3d <- ggplot(projected, aes(projected_x, projected_y, color = condition, label = sample_id)) +
        geom_point(size = 4) +
        geom_text(hjust = 1.08, vjust = -0.55, size = 3, show.legend = FALSE) +
        scale_color_manual(values = setNames(c("#1e655d", "#a15d14"), c(reference_group, case_group))) +
        scale_x_continuous(expand = expansion(mult = c(0.20, 0.12))) +
        labs(
          title = paste("3D PCA projection -", analysis_name, comparison_label),
          x = "PC1 with PC3 projection",
          y = "PC2 with PC3 projection"
        ) +
        theme_bw(base_size = 12) +
        theme(legend.position = "bottom")
      save_ggplot(pca_3d, file.path(figure_dir, "3D_PCA_plot"), 9, 6)
      write_pca_html(
        pca_df,
        round(variance, 1),
        file.path(figure_dir, "3D_PCA_plot.html"),
        paste("3D PCA -", analysis_name, comparison_label),
        case_group
      )
      record_artifact_file(
        comparison_id,
        class_label,
        "3D PCA plot",
        file.path(figure_dir, "3D_PCA_plot.png")
      )
      record_artifact_file(
        comparison_id,
        class_label,
        "3D PCA HTML",
        file.path(figure_dir, "3D_PCA_plot.html")
      )
    } else {
      pc3_rationale <- paste(
        "Fewer than three principal components available (found",
        n_pc,
        "); PC3 is required for 3D PCA artifacts"
      )
      record_artifact_skipped(comparison_id, class_label, "3D PCA plot", pc3_rationale)
      record_artifact_skipped(comparison_id, class_label, "3D PCA HTML", pc3_rationale)
    }

    heatmap_genes <- head(significant$gene_id, 50)
    heatmap_matrix <- rlog_matrix[intersect(heatmap_genes, rownames(rlog_matrix)), , drop = FALSE]
    heatmap_path <- file.path(figure_dir, "Heatmap_topDEG_rlog.png")
    if (nrow(heatmap_matrix) >= 2) {
      plot_heatmap(
        heatmap_matrix,
        selected_samples$condition,
        case_group,
        heatmap_path,
        paste("Top differential", analysis_name, "genes")
      )
      record_artifact_file(comparison_id, class_label, "top-gene heatmap", heatmap_path)
    } else {
      record_artifact_skipped(
        comparison_id,
        class_label,
        "top-gene heatmap",
        paste("Fewer than two genes available for heatmap (found", nrow(heatmap_matrix), ")")
      )
    }

    result_df$category <- ifelse(
      !is.na(result_df$padj) & result_df$padj < q_value & result_df$log2FoldChange > lfc_threshold,
      "Up",
      ifelse(
        !is.na(result_df$padj) & result_df$padj < q_value & result_df$log2FoldChange < -lfc_threshold,
        "Down",
        "Not significant"
      )
    )
    result_df$minus_log10_padj <- -log10(pmax(result_df$padj, .Machine$double.xmin))
    # The volcano plot combines effect size (x) and statistical evidence (y).
    volcano <- ggplot(
      result_df[is.finite(result_df$log2FoldChange) & is.finite(result_df$minus_log10_padj), ],
      aes(log2FoldChange, minus_log10_padj, color = category)
    ) +
      geom_point(alpha = 0.55, size = 1.1) +
      geom_vline(xintercept = c(-lfc_threshold, lfc_threshold), linetype = 2, color = "#617370") +
      geom_hline(yintercept = -log10(q_value), linetype = 2, color = "#617370") +
      scale_color_manual(values = c(Down = "#336b89", `Not significant` = "#a7b4b1", Up = "#a23b3b")) +
      labs(
        title = paste("Volcano plot -", analysis_name, comparison_label),
        x = "Shrunken log2 fold change (numerator vs denominator)",
        y = "-log10 adjusted p-value",
        color = NULL
      ) +
      theme_bw(base_size = 12) +
      theme(legend.position = "bottom")
    save_ggplot(volcano, file.path(figure_dir, "Volcano_plot"))
    record_artifact_file(comparison_id, class_label, "volcano plot", file.path(figure_dir, "Volcano_plot.png"))

    ma_data <- result_df[is.finite(result_df$baseMean) & is.finite(result_df$log2FoldChange), ]
    ma_plot <- ggplot(ma_data, aes(log10(baseMean + 1), log2FoldChange, color = category)) +
      geom_point(alpha = 0.5, size = 1) +
      geom_hline(yintercept = c(-lfc_threshold, 0, lfc_threshold), linetype = c(2, 1, 2), color = "#617370") +
      scale_color_manual(values = c(Down = "#336b89", `Not significant` = "#a7b4b1", Up = "#a23b3b")) +
      labs(
        title = paste("MA plot -", analysis_name, comparison_label),
        x = "log10 mean normalized count + 1",
        y = "Shrunken log2 fold change (numerator vs denominator)",
        color = NULL
      ) +
      theme_bw(base_size = 12) +
      theme(legend.position = "bottom")
    save_ggplot(ma_plot, file.path(figure_dir, "MA_plot"))
    record_artifact_file(comparison_id, class_label, "MA plot", file.path(figure_dir, "MA_plot.png"))

    p_hist <- ggplot(result_df[is.finite(result_df$pvalue), ], aes(pvalue)) +
      geom_histogram(bins = 40, fill = "#1e655d", color = "white") +
      labs(title = paste("P-value distribution -", analysis_name), x = "P-value", y = "Genes") +
      theme_bw(base_size = 12)
    save_ggplot(p_hist, file.path(figure_dir, "Pvalue_histogram"))
    record_artifact_file(
      comparison_id,
      class_label,
      "p-value histogram",
      file.path(figure_dir, "Pvalue_histogram.png")
    )
    padj_hist <- ggplot(result_df[is.finite(result_df$padj), ], aes(padj)) +
      geom_histogram(bins = 40, fill = "#336b89", color = "white") +
      labs(title = paste("Adjusted p-value distribution -", analysis_name), x = "Adjusted p-value", y = "Genes") +
      theme_bw(base_size = 12)
    save_ggplot(padj_hist, file.path(figure_dir, "Padj_histogram"))
    record_artifact_file(
      comparison_id,
      class_label,
      "adjusted p-value histogram",
      file.path(figure_dir, "Padj_histogram.png")
    )
    lfc_density <- ggplot(result_df[is.finite(result_df$log2FoldChange), ], aes(log2FoldChange)) +
      geom_density(fill = "#dcece6", color = "#1e655d") +
      geom_vline(xintercept = c(-lfc_threshold, lfc_threshold), linetype = 2) +
      labs(title = paste("Fold-change density -", analysis_name), x = "Shrunken log2 fold change", y = "Density") +
      theme_bw(base_size = 12)
    save_ggplot(lfc_density, file.path(figure_dir, "LFC_density"))
    record_artifact_file(comparison_id, class_label, "fold-change density", file.path(figure_dir, "LFC_density.png"))

    sample_distances <- as.matrix(dist(t(rlog_matrix)))
    sample_distance_path <- file.path(figure_dir, "Sample_distance_heatmap.png")
    png(sample_distance_path, width = 1000, height = 900, res = 130)
    tryCatch(
      heatmap(
        sample_distances,
        symm = TRUE,
        col = colorRampPalette(c("#ffffff", "#1e655d"))(100),
        margins = c(9, 9),
        main = paste("Sample distances -", analysis_name)
      ),
      finally = dev.off()
    )
    record_artifact_file(comparison_id, class_label, "sample-distance heatmap", sample_distance_path)

    counts_df <- data.frame(
      direction = factor(c("Up", "Down"), levels = c("Up", "Down")),
      genes = c(nrow(up), nrow(down))
    )
    count_plot <- ggplot(counts_df, aes(direction, genes, fill = direction)) +
      geom_col(width = 0.65) +
      scale_fill_manual(values = c(Up = "#a23b3b", Down = "#336b89"), guide = "none") +
      labs(title = paste("Differential genes -", analysis_name, comparison_label), x = NULL, y = "Genes") +
      theme_bw(base_size = 12)
    save_ggplot(count_plot, file.path(figure_dir, "DE_counts_by_comparison"), 7, 5)
    total_plot <- ggplot(data.frame(comparison = comparison_id, genes = nrow(significant)), aes(comparison, genes)) +
      geom_col(fill = "#1e655d", width = 0.55) +
      labs(title = paste("Total differential genes -", analysis_name), x = NULL, y = "Genes") +
      theme_bw(base_size = 12)
    save_ggplot(total_plot, file.path(figure_dir, "DE_totals_by_comparison"), 7, 5)
    record_artifact_file(
      comparison_id,
      class_label,
      "DE counts by comparison plot",
      file.path(figure_dir, "DE_counts_by_comparison.png")
    )
    record_artifact_file(
      comparison_id,
      class_label,
      "DE totals by comparison plot",
      file.path(figure_dir, "DE_totals_by_comparison.png")
    )
    if (analysis_name == "all_genes") {
      generate_custom_figures(
        comparison_id, class_label, result_df, rlog_matrix,
        counts(dds, normalized = TRUE), selected_samples, significant
      )
    }

    status <- data.frame(
      analysis = analysis_name,
      comparison = comparison_id,
      reference = reference_group,
      case = case_group,
      reference_samples = unname(condition_counts[[reference_group]]),
      case_samples = unname(condition_counts[[case_group]]),
      tested_genes = nrow(result_df),
      significant_genes = nrow(significant),
      upregulated = nrow(up),
      downregulated = nrow(down),
      q_value = q_value,
      absolute_lfc = lfc_threshold,
      stringsAsFactors = FALSE
    )
    write.table(status, file.path(table_dir, "comparison_status.tsv"), sep = "\t", quote = FALSE, row.names = FALSE)
    record_artifact_file(
      comparison_id,
      class_label,
      "comparison status table",
      file.path(table_dir, "comparison_status.tsv")
    )
    analysis_results[[analysis_name]] <- list(status = status, significant = significant)
    if (analysis_name %in% names(optional_de_generated)) {
      optional_de_generated[[analysis_name]] <- TRUE
    }
    status_index <- status_index + 1
    all_statuses[[status_index]] <- status
  }

  summary_dir <- file.path(output_root, "tables", "summary", comparison_id)
  summary_figure_dir <- file.path(output_root, "figures", "summary", comparison_id)
  dir.create(summary_dir, recursive = TRUE, showWarnings = FALSE)
  dir.create(summary_figure_dir, recursive = TRUE, showWarnings = FALSE)
  if (length(analysis_results) > 0) {
    summary_table <- do.call(rbind, lapply(analysis_results, `[[`, "status"))
    write.table(
      summary_table,
      file.path(summary_dir, "differential_expression_summary.tsv"),
      sep = "\t",
      quote = FALSE,
      row.names = FALSE
    )

    long_counts <- rbind(
      data.frame(analysis = summary_table$analysis, direction = "Up", genes = summary_table$upregulated),
      data.frame(analysis = summary_table$analysis, direction = "Down", genes = summary_table$downregulated)
    )
    stacked <- ggplot(long_counts, aes(analysis, genes, fill = direction)) +
      geom_col() +
      scale_fill_manual(values = c(Up = "#a23b3b", Down = "#336b89")) +
      labs(title = paste("Differential genes -", comparison_label), x = "Analysis", y = "Genes", fill = NULL) +
      theme_bw(base_size = 12) +
      theme(legend.position = "bottom")
    ggsave(file.path(summary_figure_dir, "StackedPlot_DEGs.pdf"), stacked, width = 8, height = 5)

    sig_sets <- lapply(analysis_results, function(entry) entry$significant$gene_id)
    common_between_gene_classes <- if (length(sig_sets) >= 2) {
      Reduce(intersect, sig_sets)
    } else {
      character(0)
    }
    overlap_summary <- data.frame(
      analysis = summary_table$analysis,
      unique = summary_table$significant_genes,
      common_between_gene_classes = length(common_between_gene_classes),
      stringsAsFactors = FALSE
    )
    overlap_long <- rbind(
      data.frame(analysis = overlap_summary$analysis, category = "Unique to gene class", genes = overlap_summary$unique),
      data.frame(
        analysis = overlap_summary$analysis,
        category = "Common between gene classes",
        genes = overlap_summary$common_between_gene_classes
      )
    )
    grouped <- ggplot(overlap_long, aes(analysis, genes, fill = category)) +
      geom_col(position = "dodge") +
      scale_fill_manual(values = c(`Unique to gene class` = "#1e655d", `Common between gene classes` = "#a15d14")) +
      labs(title = "Differential gene-class summary", x = "Analysis", y = "Genes", fill = NULL) +
      theme_bw(base_size = 12) +
      theme(legend.position = "bottom")
    ggsave(file.path(summary_figure_dir, "GroupedPlot_Unique_vs_Common.pdf"), grouped, width = 8, height = 5)
    write.table(
      overlap_summary,
      file.path(summary_dir, "gene_class_overlap_status.tsv"),
      sep = "\t",
      quote = FALSE,
      row.names = FALSE
    )
  }
}

# =============================================================================
# SECTION 7: CROSS-COMPARISON SUMMARY EXPORTS
# =============================================================================
# APPENDIX: 7.1
# After all comparisons finish, combine their recorded status rows into the
# existing project-level summary tables and figures.

summary_root <- file.path(output_root, "tables", "summary")
dir.create(summary_root, recursive = TRUE, showWarnings = FALSE)
if (length(all_statuses) > 0) {
  write.table(
    do.call(rbind, all_statuses),
    file.path(summary_root, "differential_expression_summary.tsv"),
    sep = "\t",
    quote = FALSE,
    row.names = FALSE
  )
}
if (length(optional_skip_log) > 0) {
  write.table(
    do.call(rbind, optional_skip_log),
    file.path(summary_root, "optional_gene_class_skips.tsv"),
    sep = "\t",
    quote = FALSE,
    row.names = FALSE
  )
}
if (length(custom_figure_metadata_rows) > 0) {
  metadata_path <- file.path(summary_root, "custom_figure_metadata.tsv")
  write.table(do.call(rbind, custom_figure_metadata_rows), metadata_path, sep = "\t", quote = FALSE, row.names = FALSE)
  record_artifact_file("", "summary", "custom figure metadata", metadata_path)
}

versions <- data.frame(
  component = c("R", "DESeq2", "tximport", "ggplot2"),
  version = c(
    R.version.string,
    as.character(packageVersion("DESeq2")),
    as.character(packageVersion("tximport")),
    as.character(packageVersion("ggplot2"))
  ),
  stringsAsFactors = FALSE
)
write.table(versions, file.path(provenance_dir, "software_versions.tsv"), sep = "\t", quote = FALSE, row.names = FALSE)
write.table(versions, file.path(summary_root, "software_versions.tsv"), sep = "\t", quote = FALSE, row.names = FALSE)

provenance_artifacts <- list(
  list(name = "sample metadata table", path = file.path(provenance_dir, "sample_metadata.tsv")),
  list(name = "reference mapping summary table", path = file.path(provenance_dir, "reference_mapping_summary.tsv")),
  list(name = "analysis parameters table", path = file.path(provenance_dir, "analysis_parameters.tsv")),
  list(name = "software versions table", path = file.path(provenance_dir, "software_versions.tsv"))
)
for (entry in provenance_artifacts) {
  record_artifact_file("", "provenance", entry$name, entry$path)
}
if (length(all_statuses) > 0) {
  summary_path <- file.path(summary_root, "differential_expression_summary.tsv")
  record_artifact_file("", "summary", "differential expression summary table", summary_path)
}
if (length(optional_skip_log) > 0) {
  skip_path <- file.path(summary_root, "optional_gene_class_skips.tsv")
  record_artifact_file("", "summary", "optional gene class skip log", skip_path)
}
record_artifact_file("", "summary", "software versions table", file.path(summary_root, "software_versions.tsv"))

if (length(output_contract_rows) == 0) {
  stop("No output contract rows were recorded")
}
write.table(
  do.call(rbind, output_contract_rows),
  file.path(summary_root, "output_contract.tsv"),
  sep = "\t",
  quote = FALSE,
  row.names = FALSE
)
progress_message("Analysis complete")

# =============================================================================
# APPENDICES: PLAIN-ENGLISH PSEUDOCODE
# =============================================================================
# These appendices describe the existing functions and major analysis blocks.
# They are explanatory only and do not change the statistical analysis.
#
# SECTION 1
# Appendix 1.1 — Send a progress message to the workflow log immediately.
# Appendix 1.2 — Read ten arguments, validate settings and input tables, then create result directories.
#
# SECTION 2
# Appendix 2.1 — Read, clean, deduplicate, and validate transcript-to-gene mappings.
# Appendix 2.2 — Import Kallisto abundance tables with tximport using that validated mapping.
#
# SECTION 3
# Appendix 3.1 — Save one ggplot as both PNG and PDF.
# Appendix 3.2 — Draw and save a scaled expression heatmap with sample-group colors.
# Appendix 3.3 — Escape special text before inserting it into HTML.
# Appendix 3.4 — Project calculated PCA coordinates into a self-contained HTML SVG plot.
# Appendix 3.5 — Write the reason an optional analysis class was skipped.
#
# SECTION 4
# Appendix 4.1 — Build all-gene, mRNA, and lncRNA gene sets, recording unavailable classes.
# Appendix 4.2 — Convert the internal all_genes name to the reader-facing all-gene label.
# Appendix 4.3 — Return true only for an existing, non-empty output file.
# Appendix 4.4 — Convert an absolute result path into a portable path relative to the output root.
# Appendix 4.5 — Add one status row to the in-memory output contract.
# Appendix 4.6 — Record a generated file as successful, or record its expected path as failed.
# Appendix 4.7 — Record an intentionally skipped artifact with its explanation.
#
# SECTION 5
# Appendix 5.1 — Make a safe, timestamped, unique filename stem for a custom figure.
# Appendix 5.2 — Apply valid user-requested x/y limits without discarding plotted data.
# Appendix 5.3 — Return the requested DESeq2 result metric, or no value for an unsupported metric.
# Appendix 5.4 — Create each requested custom figure from existing results and record its outcome.
# Appendix 5.5 — Mark every standard artifact as skipped when its gene class is unavailable.
#
# SECTION 6
# Appendix 6.1 — Fit DESeq2 normally; for very small gene sets, use the documented gene-wise fallback.
# Appendix 6.2 — For each comparison, select samples, fit the requested design, export results and figures, and record provenance.
#
# SECTION 7
# Appendix 7.1 — Combine per-comparison statuses and export cross-comparison summaries, software versions, and the output contract.
