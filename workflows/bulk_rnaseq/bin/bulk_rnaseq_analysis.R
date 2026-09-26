#!/usr/bin/env Rscript

# Optional gene-class outputs use exact biotype matches only (no pattern grep).
# Accepted lncRNA gene_biotype values are listed in ACCEPTED_LNCRNA_GENE_BIOTYPES
# below and in workflows/bulk_rnaseq/README.md.
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
if (length(args) != 7) {
  stop(
    "Usage: bulk_rnaseq_analysis.R <samples.tsv> <transcript_to_gene.tsv> <output> ",
    "<comparisons.tsv> <q-value> <absolute-lfc> <minimum-group-size>"
  )
}

sample_sheet_path <- args[[1]]
mapping_path <- args[[2]]
output_root <- args[[3]]
comparison_sheet_path <- args[[4]]
q_value <- as.numeric(args[[5]])
lfc_threshold <- as.numeric(args[[6]])
minimum_group_size <- as.integer(args[[7]])
if (!is.finite(q_value) || q_value <= 0 || q_value > 1) stop("Adjusted p-value must be in (0, 1]")
if (!is.finite(lfc_threshold) || lfc_threshold < 0) stop("Absolute log2 fold change must be non-negative")
if (is.na(minimum_group_size) || minimum_group_size < 2) stop("Minimum group size must be at least 2")

for (directory in c("differential_expression", "figures", "tables")) {
  dir.create(file.path(output_root, directory), recursive = TRUE, showWarnings = FALSE)
}
provenance_dir <- file.path(output_root, "tables", "provenance")
dir.create(provenance_dir, recursive = TRUE, showWarnings = FALSE)

samples <- read.delim(sample_sheet_path, stringsAsFactors = FALSE, check.names = FALSE)
required_columns <- c("sample_id", "condition", "intervention", "abundance_tsv")
if (!all(required_columns %in% colnames(samples))) {
  stop("Sample sheet must contain sample_id, condition, intervention, and abundance_tsv columns")
}
if (anyDuplicated(samples$sample_id)) stop("Sample identifiers must be unique")
if (!all(file.exists(samples$abundance_tsv))) stop("One or more abundance tables are missing")

comparisons <- read.delim(comparison_sheet_path, stringsAsFactors = FALSE, check.names = FALSE)
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

read_transcript_to_gene <- function(path) {
  mapping <- read.delim(path, stringsAsFactors = FALSE, check.names = FALSE)
  required <- c("transcript_id", "gene_id")
  if (!all(required %in% colnames(mapping))) {
    stop("Transcript-to-gene mapping must contain transcript_id and gene_id columns")
  }
  mapping <- mapping[!is.na(mapping$transcript_id) & nzchar(mapping$transcript_id), , drop = FALSE]
  mapping <- mapping[!is.na(mapping$gene_id) & nzchar(mapping$gene_id), , drop = FALSE]
  if (nrow(mapping) == 0) stop("Transcript-to-gene mapping contains no usable rows")
  mapping <- mapping[!duplicated(mapping$transcript_id), , drop = FALSE]
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
  samples[, c("sample_id", "condition", "intervention"), drop = FALSE],
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
      "design_formula",
      "log2_fold_change_numerator",
      "log2_fold_change_denominator"
    ),
    value = c(
      q_value,
      lfc_threshold,
      minimum_group_size,
      "~condition",
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
names(quant_files) <- samples$sample_id
txi <- tximport(
  quant_files,
  type = "kallisto",
  tx2gene = tx2gene,
  ignoreAfterBar = TRUE,
  dropInfReps = TRUE,
  countsFromAbundance = "no"
)

save_ggplot <- function(plot, stem, width = 8, height = 6) {
  ggsave(paste0(stem, ".png"), plot, width = width, height = height, dpi = 160)
  ggsave(paste0(stem, ".pdf"), plot, width = width, height = height)
}

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

html_escape <- function(value) {
  value <- gsub("&", "&amp;", value, fixed = TRUE)
  value <- gsub("<", "&lt;", value, fixed = TRUE)
  value <- gsub(">", "&gt;", value, fixed = TRUE)
  value
}

write_pca_html <- function(pca_df, percent_var, filename, title, case_group) {
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

write_skip_rationale <- function(output_root, analysis_name, comparison_id, rationale) {
  table_dir <- file.path(output_root, "tables", analysis_name, comparison_id)
  dir.create(table_dir, recursive = TRUE, showWarnings = FALSE)
  writeLines(rationale, file.path(table_dir, "skip_rationale.txt"), useBytes = TRUE)
}

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

for (comparison_index in seq_len(nrow(comparisons))) {
  comparison_id <- comparisons$comparison_id[[comparison_index]]
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
  }

  analysis_results <- list()

  for (analysis_name in names(analysis_classes)) {
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

    dds <- DESeqDataSetFromTximport(class_txi, colData = col_data, design = ~condition)
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
      next
    }
    dds <- DESeq(dds, quiet = TRUE)
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
    significant <- result_df[
      !is.na(result_df$padj) & result_df$padj < q_value & abs(result_df$log2FoldChange) > lfc_threshold,
    ]
    up <- significant[significant$log2FoldChange > lfc_threshold, ]
    down <- significant[significant$log2FoldChange < -lfc_threshold, ]
    threshold_suffix <- paste0(
      "padj", format(q_value, trim = TRUE, scientific = FALSE),
      "_lfc", format(lfc_threshold, trim = TRUE, scientific = FALSE)
    )

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
    write.table(
      as.data.frame(counts(dds, normalized = TRUE)),
      file.path(table_dir, "library_size_normalized_counts.tsv"),
      sep = "\t",
      quote = FALSE,
      col.names = NA
    )

    rld <- rlog(dds, blind = FALSE)
    rlog_matrix <- assay(rld)
    write.table(
      as.data.frame(rlog_matrix),
      file.path(table_dir, "rlog_normalized_expression.tsv"),
      sep = "\t",
      quote = FALSE,
      col.names = NA
    )

    pca <- prcomp(t(rlog_matrix), scale. = FALSE)
    variance <- 100 * pca$sdev^2 / sum(pca$sdev^2)
    pca_df <- data.frame(
      sample_id = rownames(pca$x),
      condition = col_data[rownames(pca$x), "condition"],
      PC1 = pca$x[, 1],
      PC2 = pca$x[, 2],
      PC3 = pca$x[, 3],
      stringsAsFactors = FALSE
    )
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

    scree_df <- data.frame(
      component = factor(paste0("PC", seq_along(variance)), levels = paste0("PC", seq_along(variance))),
      variance = variance
    )
    scree_plot <- ggplot(scree_df, aes(component, variance)) +
      geom_col(fill = "#1e655d") +
      labs(title = "Scree plot", x = "Principal component", y = "Variance explained (%)") +
      theme_minimal(base_size = 12) +
      theme(axis.text.x = element_text(angle = 60, hjust = 1))
    ggsave(file.path(figure_dir, "Scree_plot.png"), scree_plot, width = 8, height = 5, dpi = 160)

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

    ranked <- result_df[!is.na(result_df$pvalue), ]
    heatmap_genes <- if (nrow(significant) >= 2) head(significant$gene_id, 50) else head(ranked$gene_id, 50)
    heatmap_matrix <- rlog_matrix[intersect(heatmap_genes, rownames(rlog_matrix)), , drop = FALSE]
    if (nrow(heatmap_matrix) >= 2) {
      plot_heatmap(
        heatmap_matrix,
        selected_samples$condition,
        case_group,
        file.path(figure_dir, "Heatmap_topDEG_rlog.png"),
        paste("Top differential", analysis_name, "genes")
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

    p_hist <- ggplot(result_df[is.finite(result_df$pvalue), ], aes(pvalue)) +
      geom_histogram(bins = 40, fill = "#1e655d", color = "white") +
      labs(title = paste("P-value distribution -", analysis_name), x = "P-value", y = "Genes") +
      theme_bw(base_size = 12)
    save_ggplot(p_hist, file.path(figure_dir, "Pvalue_histogram"))
    padj_hist <- ggplot(result_df[is.finite(result_df$padj), ], aes(padj)) +
      geom_histogram(bins = 40, fill = "#336b89", color = "white") +
      labs(title = paste("Adjusted p-value distribution -", analysis_name), x = "Adjusted p-value", y = "Genes") +
      theme_bw(base_size = 12)
    save_ggplot(padj_hist, file.path(figure_dir, "Padj_histogram"))
    lfc_density <- ggplot(result_df[is.finite(result_df$log2FoldChange), ], aes(log2FoldChange)) +
      geom_density(fill = "#dcece6", color = "#1e655d") +
      geom_vline(xintercept = c(-lfc_threshold, lfc_threshold), linetype = 2) +
      labs(title = paste("Fold-change density -", analysis_name), x = "Shrunken log2 fold change", y = "Density") +
      theme_bw(base_size = 12)
    save_ggplot(lfc_density, file.path(figure_dir, "LFC_density"))

    sample_distances <- as.matrix(dist(t(rlog_matrix)))
    png(file.path(figure_dir, "Sample_distance_heatmap.png"), width = 1000, height = 900, res = 130)
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
optional_output_status <- function(name) {
  if (isTRUE(optional_de_generated[[name]])) "generated" else "skipped"
}
write.table(
  data.frame(
    output = c(
      "all-gene DE tables",
      "optional mRNA DE tables",
      "optional lncRNA DE tables",
      "3D PCA",
      "2D PCA",
      "scree plot",
      "top-gene heatmap",
      "volcano plot",
      "MA plot",
      "p-value histogram",
      "adjusted p-value histogram",
      "fold-change density",
      "sample-distance heatmap",
      "DE count plots",
      "normalized matrices",
      "provenance tables"
    ),
    status = c(
      "generated",
      optional_output_status("mRNA"),
      optional_output_status("lncRNA"),
      rep("generated", 13)
    ),
    stringsAsFactors = FALSE
  ),
  file.path(summary_root, "output_contract.tsv"),
  sep = "\t",
  quote = FALSE,
  row.names = FALSE
)
