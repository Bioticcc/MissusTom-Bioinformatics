#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(data.table)
  library(ggplot2)
  library(ggrepel)
  library(scales)
  library(patchwork)
  library(GenomicRanges)
  library(IRanges)
  library(GenomeInfoDb)
  library(rtracklayer)
  library(jsonlite)
})

options(stringsAsFactors = FALSE, scipen = 999)

`%||%` <- function(value, fallback) {
  if (is.null(value) || length(value) == 0L || is.na(value) || value == "") fallback else value
}

parse_options <- function(arguments) {
  if (length(arguments) %% 2L != 0L) {
    stop("Every Stage 05 R option must have a value")
  }
  keys <- sub("^--", "", arguments[seq(1L, length(arguments), by = 2L)])
  values <- arguments[seq(2L, length(arguments), by = 2L)]
  if (any(!startsWith(arguments[seq(1L, length(arguments), by = 2L)], "--"))) {
    stop("Stage 05 R options must begin with --")
  }
  as.list(setNames(values, keys))
}

opt <- parse_options(commandArgs(trailingOnly = TRUE))
required_options <- c(
  "sample-id", "reference-name", "fai", "global-levels",
  "chromosome-methylation", "call-coverage", "window-methylation",
  "chromosome-coverage", "window-coverage", "alignment-stats",
  "alignment-flagstat", "coverage-summary", "stage02-summary",
  "instrument-report", "bedmethyl", "gff3",
  "cpg-islands", "ccre", "intergenic", "output-dir",
  "min-valid-coverage", "min-feature-cpgs", "top-window-count", "plot-dpi"
)
missing_options <- required_options[!required_options %in% names(opt)]
if (length(missing_options) > 0L) {
  stop("Missing Stage 05 R option(s): ", paste(missing_options, collapse = ", "))
}

sample_id <- opt[["sample-id"]]
reference_name <- opt[["reference-name"]]
output_dir <- normalizePath(opt[["output-dir"]], mustWork = FALSE)
tables_dir <- file.path(output_dir, "tables")
figures_dir <- file.path(output_dir, "figures")
dir.create(tables_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(figures_dir, recursive = TRUE, showWarnings = FALSE)

min_valid_coverage <- as.integer(opt[["min-valid-coverage"]])
min_feature_cpgs <- as.integer(opt[["min-feature-cpgs"]])
top_window_count <- as.integer(opt[["top-window-count"]])
plot_dpi <- as.integer(opt[["plot-dpi"]])
max_cpg_sites <- as.integer(opt[["max-cpg-sites"]] %||% "0")
if (any(!is.finite(c(min_valid_coverage, min_feature_cpgs, top_window_count, plot_dpi, max_cpg_sites))) ||
    min_valid_coverage < 1L || min_feature_cpgs < 1L || top_window_count < 1L ||
    plot_dpi < 72L || max_cpg_sites < 0L) {
  stop("Invalid numeric Stage 05 R option")
}

input_paths <- unlist(opt[c(
  "fai", "global-levels", "chromosome-methylation", "call-coverage",
  "window-methylation", "chromosome-coverage", "window-coverage",
  "alignment-stats", "alignment-flagstat", "coverage-summary", "stage02-summary",
  "instrument-report", "bedmethyl", "gff3", "cpg-islands", "ccre", "intergenic"
)])
missing_inputs <- input_paths[!file.exists(input_paths) | file.info(input_paths)$size <= 0]
if (length(missing_inputs) > 0L) {
  stop("Missing or empty Stage 05 input: ", missing_inputs[[1L]])
}

message("Stage 05 R analysis for ", sample_id)
message("Output directory: ", output_dir)
message("Feature methylation minimum valid coverage: ", min_valid_coverage, "x")

theme_set(
  theme_bw(base_size = 11) +
    theme(
      plot.title = element_text(face = "bold"),
      plot.subtitle = element_text(color = "grey30"),
      panel.grid.minor = element_blank(),
      legend.position = "right"
    )
)

modification_colors <- c(
  "Canonical C" = "#B8B8B8",
  "5mC" = "#2C7FB8",
  "5hmC" = "#F28E2B",
  "Total modified" = "#6A51A3"
)

read_tsv <- function(path) {
  if (grepl("[.]gz$", path)) {
    result <- fread(cmd = paste("gzip -cd", shQuote(path)), sep = "\t", header = TRUE,
                    na.strings = c("NA", ""), check.names = FALSE)
  } else {
    result <- fread(path, sep = "\t", header = TRUE, na.strings = c("NA", ""),
                    check.names = FALSE)
  }
  if ("#chrom" %in% names(result)) setnames(result, "#chrom", "chrom")
  result
}

atomic_fwrite <- function(table, path, compress = FALSE) {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  suffix <- if (compress) ".partial.gz" else ".partial"
  partial <- paste0(path, suffix)
  fwrite(table, partial, sep = "\t", quote = FALSE, na = "NA",
         compress = if (compress) "gzip" else "none")
  if (!file.rename(partial, path)) stop("Could not promote table: ", path)
}

save_plot <- function(plot, stem, width = 9, height = 6) {
  pdf_path <- file.path(figures_dir, paste0(stem, ".pdf"))
  ggsave(pdf_path, plot = plot, width = width, height = height, units = "in",
         device = cairo_pdf, bg = "white")
  # Optional raster export (enable when PNG figures are specifically needed):
  # png_path <- file.path(figures_dir, paste0(stem, ".png"))
  # ggsave(png_path, plot = plot, width = width, height = height, units = "in",
  #        dpi = plot_dpi, bg = "white")
  message("Saved figure: ", stem)
}

chromosome_order <- c(paste0("chr", 1:19), "chrX", "chrY", "chrM")
is_main_chromosome <- function(chrom) chrom %chin% chromosome_order

fai <- fread(opt[["fai"]], sep = "\t", header = FALSE, select = 1:2,
             col.names = c("chrom", "length"))
fai <- fai[chrom %chin% chromosome_order]
fai[, chrom := factor(chrom, levels = chromosome_order)]
setorder(fai, chrom)
fai[, chrom := as.character(chrom)]
if (nrow(fai) < 22L) stop("Reference FAI lacks one or more main mouse chromosomes")

global_levels <- read_tsv(opt[["global-levels"]])
chrom_methylation <- read_tsv(opt[["chromosome-methylation"]])
call_coverage <- read_tsv(opt[["call-coverage"]])
window_methylation <- read_tsv(opt[["window-methylation"]])
chrom_coverage <- read_tsv(opt[["chromosome-coverage"]])
window_coverage <- read_tsv(opt[["window-coverage"]])
coverage_summary <- read_tsv(opt[["coverage-summary"]])

# Read one row per CpG dyad. The m row already contains 5mC in column 12 and
# the cross-matched 5hmC count in column 14, so the paired h row is unnecessary.
awk_program <- if (max_cpg_sites > 0L) {
  sprintf('$4 == "m" {print; seen++; if (seen >= %d) exit}', max_cpg_sites)
} else {
  '$4 == "m" {print}'
}
cpg_command <- sprintf("gzip -cd %s | awk -F '\\t' '%s'", shQuote(opt[["bedmethyl"]]), awk_program)
message("Reading validated CpG count rows")
cpg <- fread(
  cmd = cpg_command,
  sep = "\t",
  header = FALSE,
  select = c(1L, 2L, 3L, 10L, 12L, 13L, 14L, 15L, 16L, 17L, 18L),
  col.names = c(
    "chrom", "start", "end", "valid_calls", "modified_5mc_calls",
    "canonical_calls", "modified_5hmc_calls", "deletion_calls",
    "failed_filtered_calls", "different_base_calls", "no_call_calls"
  )
)
if (nrow(cpg) == 0L) stop("No 5mC CpG rows were read")
cpg[, total_observations := valid_calls + deletion_calls + failed_filtered_calls +
      different_base_calls + no_call_calls]
cpg[, `:=`(
  pct_5mc = 100 * modified_5mc_calls / valid_calls,
  pct_5hmc = 100 * modified_5hmc_calls / valid_calls,
  pct_total_modified = 100 * (modified_5mc_calls + modified_5hmc_calls) / valid_calls
)]
if (any(cpg$valid_calls == 65535L)) stop("Stage 05 found the forbidden 65,535 saturation sentinel")
if (any(cpg$valid_calls != cpg$modified_5mc_calls + cpg$modified_5hmc_calls + cpg$canonical_calls)) {
  stop("Stage 05 found an invalid CpG valid-coverage identity")
}
message("CpG sites loaded: ", format(nrow(cpg), big.mark = ","))

# ------------------------------
# Global and CpG-level plot data
# ------------------------------
composition <- data.table(
  sample = sample_id,
  category = factor(c("Canonical C", "5mC", "5hmC"),
                    levels = c("Canonical C", "5mC", "5hmC")),
  call_count = c(
    global_levels[category == "canonical_C", call_count],
    global_levels[category == "5mC", call_count],
    global_levels[category == "5hmC", call_count]
  )
)
composition[, percent := 100 * call_count / sum(call_count)]
atomic_fwrite(composition, file.path(tables_dir, "global_plot_data.tsv"))

p_composition <- ggplot(composition, aes(sample, percent, fill = category)) +
  geom_col(width = 0.58, color = "white", linewidth = 0.3) +
  geom_text(aes(label = ifelse(percent >= 1, sprintf("%.2f%%", percent), "")),
            position = position_stack(vjust = 0.5), size = 3.5) +
  scale_fill_manual(values = modification_colors, drop = FALSE) +
  scale_y_continuous(limits = c(0, 100), expand = expansion(mult = c(0, 0.02))) +
  labs(
    title = "Global CpG modification composition",
    subtitle = "Coverage-weighted valid cytosine calls; SixBase-compatible composition view",
    x = NULL, y = "Percentage of valid CpG calls", fill = NULL
  )
save_plot(p_composition, "01_Global_CpG_Modification_Composition", 8, 6)

global_bars <- rbindlist(list(
  global_levels[category == "5mC", .(category = "5mC", percent = percent_of_valid_calls)],
  global_levels[category == "5hmC", .(category = "5hmC", percent = percent_of_valid_calls)],
  global_levels[category == "total_modified", .(category = "Total modified", percent = percent_of_valid_calls)]
))
global_bars[, category := factor(category, levels = c("5mC", "5hmC", "Total modified"))]
p_global <- ggplot(global_bars, aes(category, percent, fill = category)) +
  geom_col(width = 0.65) +
  geom_text(aes(label = sprintf("%.2f%%", percent)), vjust = -0.35, fontface = "bold") +
  scale_fill_manual(values = modification_colors, guide = "none") +
  scale_y_continuous(expand = expansion(mult = c(0, 0.12))) +
  labs(title = "Global CpG methylation levels", x = NULL,
       y = "Percentage of valid CpG calls")
save_plot(p_global, "02_Global_CpG_Methylation_Levels", 8, 6)

coverage_distribution <- cpg[, .N, by = valid_calls][order(valid_calls)]
coverage_distribution[, fraction_of_covered_cpgs := N / sum(N)]
atomic_fwrite(coverage_distribution, file.path(tables_dir, "cpg_coverage_distribution.tsv"))
coverage_display_max <- max(30L, as.integer(quantile(cpg$valid_calls, 0.995, names = FALSE)))
coverage_display_max <- min(coverage_display_max, 100L)
p_coverage_distribution <- ggplot(
  coverage_distribution[valid_calls <= coverage_display_max],
  aes(valid_calls, fraction_of_covered_cpgs)
) +
  geom_line(color = "#2A6F7A", linewidth = 1) +
  geom_area(fill = "#6BAED6", alpha = 0.3) +
  scale_y_continuous(labels = percent_format(accuracy = 0.1)) +
  labs(
    title = "CpG valid-call coverage distribution",
    subtitle = paste0("Display truncated at the 99.5th percentile (", coverage_display_max,
                      " calls); complete counts are in the plot-data table"),
    x = "Valid modification calls per covered CpG", y = "Fraction of covered CpGs"
  )
save_plot(p_coverage_distribution, "03_CpG_Valid_Coverage_Distribution", 9, 6)

coverage_threshold_values <- c(1L, 5L, 10L, 15L, 20L, 30L)
coverage_thresholds <- data.table(minimum_valid_coverage = coverage_threshold_values)
coverage_thresholds[, `:=`(
  cpg_sites = vapply(minimum_valid_coverage, function(x) sum(cpg$valid_calls >= x), numeric(1)),
  percent_of_covered_cpgs = vapply(minimum_valid_coverage,
    function(x) 100 * mean(cpg$valid_calls >= x), numeric(1))
)]
atomic_fwrite(coverage_thresholds, file.path(tables_dir, "cpg_coverage_thresholds.tsv"))
p_thresholds <- ggplot(coverage_thresholds, aes(minimum_valid_coverage, percent_of_covered_cpgs)) +
  geom_line(color = "#4C78A8", linewidth = 1) +
  geom_point(color = "#4C78A8", size = 3) +
  geom_text(aes(label = sprintf("%.1f%%", percent_of_covered_cpgs)), vjust = -0.8, size = 3.4) +
  scale_x_continuous(breaks = coverage_threshold_values) +
  scale_y_continuous(limits = c(0, 100), expand = expansion(mult = c(0, 0.04))) +
  labs(
    title = "How much of the covered CpG dataset reaches each call depth",
    subtitle = "Coverage-threshold view reproduced from the SixBase initial QC",
    x = "Minimum valid-call coverage required", y = "Covered CpGs meeting requirement (%)"
  )
save_plot(p_thresholds, "04_CpG_Coverage_Thresholds", 9, 6)

eligible_site_indices <- which(cpg$valid_calls >= min_valid_coverage)
set.seed(42)
if (length(eligible_site_indices) > 200000L) {
  eligible_site_indices <- sort(sample(eligible_site_indices, 200000L))
}
site_plot_sample <- cpg[eligible_site_indices, .(
  chrom, start, end, valid_calls, pct_5mc, pct_5hmc, pct_total_modified
)]
atomic_fwrite(site_plot_sample, file.path(tables_dir, "cpg_site_plot_sample.tsv.gz"), compress = TRUE)
site_plot_long <- melt(
  site_plot_sample,
  measure.vars = c("pct_5mc", "pct_5hmc"),
  variable.name = "modification", value.name = "percent"
)
site_plot_long[, modification := factor(modification,
  levels = c("pct_5mc", "pct_5hmc"), labels = c("5mC", "5hmC"))]
p_site_distribution <- ggplot(site_plot_long, aes(percent, fill = modification)) +
  geom_histogram(bins = 50, boundary = 0, color = "white", linewidth = 0.15) +
  facet_wrap(~modification, scales = "free_y", ncol = 1) +
  scale_fill_manual(values = modification_colors, guide = "none") +
  labs(
    title = "CpG-site methylation distributions",
    subtitle = paste0("Deterministic sample of CpGs with at least ", min_valid_coverage,
                      " valid calls"),
    x = "Modified calls at a CpG (%)", y = "CpG sites"
  )
save_plot(p_site_distribution, "05_CpG_Site_Methylation_Distributions", 9, 8)

high_depth_sites <- cpg[total_observations >= 60000L, .(
  chrom, start, end, valid_calls, total_observations, pct_5mc, pct_5hmc,
  modified_5mc_calls, modified_5hmc_calls, canonical_calls
)]
atomic_fwrite(high_depth_sites, file.path(tables_dir, "high_depth_cpg_sites.tsv"))

# --------------------------------
# Chromosome and fixed-window plots
# --------------------------------
chromosome_plot <- merge(
  chrom_methylation[is_main_chromosome(chrom)],
  chrom_coverage[is_main_chromosome(chrom)],
  by = "chrom", suffixes = c("_calls", "_sequencing")
)
chromosome_plot[, chrom := factor(chrom, levels = chromosome_order)]
setorder(chromosome_plot, chrom)
atomic_fwrite(chromosome_plot, file.path(tables_dir, "chromosome_plot_data.tsv"))

chrom_methylation_long <- melt(
  chromosome_plot,
  id.vars = "chrom",
  measure.vars = c("pct_5mc_of_valid_calls", "pct_5hmc_of_valid_calls"),
  variable.name = "modification", value.name = "percent"
)
chrom_methylation_long[, modification := factor(modification,
  levels = c("pct_5mc_of_valid_calls", "pct_5hmc_of_valid_calls"),
  labels = c("5mC", "5hmC"))]
p_chrom_methylation <- ggplot(chrom_methylation_long, aes(chrom, percent, fill = modification)) +
  geom_col(position = "dodge", width = 0.78) +
  facet_wrap(~modification, scales = "free_y", ncol = 1) +
  scale_fill_manual(values = modification_colors, guide = "none") +
  theme(axis.text.x = element_text(angle = 45, hjust = 1)) +
  labs(title = "Chromosome-level CpG methylation", x = NULL,
       y = "Percentage of valid calls")
save_plot(p_chrom_methylation, "06_Chromosome_CpG_Methylation_Levels", 11, 8)

chrom_coverage_long <- rbindlist(list(
  chromosome_plot[, .(chrom, metric = "Reference CpGs with valid calls",
                      percent = pct_reference_cpg_sites_with_valid_calls)],
  chromosome_plot[, .(chrom, metric = "Reference bases with sequencing coverage",
                      percent = pct_ge_1x)]
))
p_chrom_coverage <- ggplot(chrom_coverage_long, aes(chrom, percent, color = metric, group = metric)) +
  geom_hline(yintercept = 80, linetype = "dashed", color = "grey55") +
  geom_line(linewidth = 0.8) + geom_point(size = 2) +
  scale_color_manual(values = c(
    "Reference CpGs with valid calls" = "#2C7FB8",
    "Reference bases with sequencing coverage" = "#59A14F"
  )) +
  scale_y_continuous(limits = c(0, 100)) +
  theme(axis.text.x = element_text(angle = 45, hjust = 1), legend.position = "bottom") +
  labs(title = "Chromosome coverage: sequencing versus modification calls",
       x = NULL, y = "Reference coverage (%)", color = NULL)
save_plot(p_chrom_coverage, "07_Chromosome_Sequencing_and_Call_Coverage", 11, 6)

p_coverage_scatter <- ggplot(
  chromosome_plot,
  aes(mean_depth, valid_calls / pmax(cpg_sites_with_valid_calls, 1), label = chrom)
) +
  geom_abline(slope = 1, intercept = 0, linetype = "dashed", color = "grey65") +
  geom_point(aes(size = cpg_sites_with_valid_calls, color = pct_5mc_of_valid_calls), alpha = 0.85) +
  geom_text_repel(
    size = 2.8,
    seed = 42,
    box.padding = 0.35,
    point.padding = 0.25,
    min.segment.length = 0,
    max.overlaps = Inf,
    show.legend = FALSE
  ) +
  scale_x_log10(labels = label_number(big.mark = ",")) +
  scale_y_log10(labels = label_number(big.mark = ",")) +
  scale_size_continuous(range = c(2, 8), labels = label_number(big.mark = ",")) +
  scale_color_viridis_c(option = "C", end = 0.9) +
  annotation_logticks(sides = "bl") +
  labs(
    title = "Sequencing depth versus valid CpG-call depth",
    subtitle = "Chromosome-level values; both axes are logarithmic",
    x = "Mean sequencing depth (log scale)",
    y = "Mean valid calls per covered CpG (log scale)",
    size = "Covered CpGs", color = "5mC (%)"
  )
save_plot(p_coverage_scatter, "08_Sequencing_vs_Modification_Call_Coverage", 9, 7)

window_plot <- merge(
  window_methylation[is_main_chromosome(chrom)],
  window_coverage[is_main_chromosome(chrom)],
  by = c("chrom", "start", "end"), suffixes = c("_calls", "_sequencing")
)
window_plot[, `:=`(
  midpoint = (start + end) / 2,
  mean_valid_calls_per_covered_cpg = valid_calls / pmax(cpg_sites_with_valid_calls, 1),
  analysis_eligible = reference_cpg_sites > 0 & valid_calls >= 100 &
    pct_reference_cpg_sites_with_valid_calls >= 80 & pct_ge_1x >= 80
)]
offset_table <- copy(fai)
offset_table[, offset := data.table::shift(cumsum(as.numeric(length)), fill = 0)]
offset_table[, chromosome_midpoint := offset + length / 2]
window_plot <- merge(window_plot, offset_table, by = "chrom", all.x = TRUE)
window_plot[, genome_midpoint := offset + midpoint]
window_plot[, chrom := factor(chrom, levels = chromosome_order)]
setorder(window_plot, chrom, start)
window_table_path <- file.path(tables_dir, "window_plot_data.tsv.gz")
atomic_fwrite(window_plot, window_table_path, compress = TRUE)

plot_manhattan_metric <- function(metric, label, stem, color) {
  eligible <- window_plot[analysis_eligible == TRUE & is.finite(get(metric))]
  chromosome_axis <- offset_table[chrom %chin% unique(as.character(eligible$chrom))]
  eligible[, alternating := as.integer(factor(chrom, levels = chromosome_order)) %% 2L]
  plot <- ggplot(eligible, aes(genome_midpoint, .data[[metric]], color = factor(alternating))) +
    geom_point(size = 0.45, alpha = 0.7) +
    scale_color_manual(values = c("0" = color, "1" = alpha(color, 0.55)), guide = "none") +
    scale_x_continuous(breaks = chromosome_axis$chromosome_midpoint,
                       labels = sub("chr", "", chromosome_axis$chrom), expand = c(0.005, 0.005)) +
    labs(title = paste0("Genome-wide ", label, " across configured windows"),
         subtitle = "Descriptive Manhattan-style track; points are methylation levels, not p-values",
         x = "Chromosome", y = paste0(label, " (% of valid calls)")) +
    theme(panel.grid.major.x = element_blank())
  save_plot(plot, stem, 13, 5.5)
}
plot_manhattan_metric("pct_5mc_of_valid_calls", "5mC", "09_Genomewide_5mC_100kb_Windows", "#2C7FB8")
plot_manhattan_metric("pct_5hmc_of_valid_calls", "5hmC", "10_Genomewide_5hmC_100kb_Windows", "#F28E2B")

eligible_windows <- window_plot[analysis_eligible == TRUE]
p_window_scatter <- ggplot(
  eligible_windows,
  aes(pct_5mc_of_valid_calls, pct_5hmc_of_valid_calls,
      color = mean_depth, size = mean_valid_calls_per_covered_cpg)
) +
  geom_point(alpha = 0.55) +
  scale_color_viridis_c(option = "D", trans = "sqrt") +
  scale_size_continuous(range = c(0.5, 4)) +
  labs(
    title = "Relationship between 5mC and 5hmC across configured windows",
    subtitle = "Single-sample analogue of the SixBase methylation scatter views",
    x = "5mC (% of valid calls)", y = "5hmC (% of valid calls)",
    color = "Sequencing depth", size = "Valid CpG-call depth"
  )
save_plot(p_window_scatter, "11_Window_5mC_vs_5hmC_Scatter", 9, 7)

heatmap_data <- copy(eligible_windows)
heatmap_data[, `:=`(
  relative_start = pmax(0, start / length),
  relative_end = pmin(1, end / length),
  chromosome_index = length(chromosome_order) + 1L -
    match(as.character(chrom), chromosome_order)
)]

make_heatmap_panel <- function(data, value_column, panel_title, show_x_axis) {
  ggplot(
    data[is.finite(get(value_column))],
    aes(
      xmin = relative_start,
      xmax = relative_end,
      ymin = chromosome_index - 0.45,
      ymax = chromosome_index + 0.45,
      fill = .data[[value_column]]
    )
  ) +
    geom_rect(color = NA) +
    scale_x_continuous(
      limits = c(0, 1),
      breaks = c(0, 0.25, 0.5, 0.75, 1),
      labels = percent_format(accuracy = 1),
      expand = expansion(mult = 0)
    ) +
    scale_y_continuous(
      breaks = seq_along(chromosome_order),
      labels = rev(chromosome_order),
      expand = expansion(add = 0.1)
    ) +
    scale_fill_viridis_c(option = "C", na.value = "grey90") +
    labs(
      title = panel_title,
      x = if (show_x_axis) "Relative position along chromosome" else NULL,
      y = NULL,
      fill = "% valid calls"
    ) +
    theme(
      panel.grid = element_blank(),
      plot.title = element_text(size = 11, hjust = 0.5),
      axis.text.x = if (show_x_axis) element_text() else element_blank(),
      axis.ticks.x = if (show_x_axis) element_line() else element_blank()
    )
}

p_5hmc_heatmap <- make_heatmap_panel(
  heatmap_data,
  "pct_5hmc_of_valid_calls",
  "5hmC",
  FALSE
)
p_5mc_heatmap <- make_heatmap_panel(
  heatmap_data,
  "pct_5mc_of_valid_calls",
  "5mC",
  TRUE
)
p_window_heatmap <- (p_5hmc_heatmap / p_5mc_heatmap) +
  plot_annotation(
    title = "Genome-wide methylation heatmaps",
    subtitle = paste0(
      "Coverage-qualified configured windows; ",
      "each modification has an independent color scale"
    ),
    theme = theme(
      plot.title = element_text(face = "bold", size = 14),
      plot.subtitle = element_text(color = "grey30", size = 10)
    )
  )
save_plot(p_window_heatmap, "12_Window_Methylation_Heatmap", 11, 8)

cpg_extents <- cpg[, .(cpg_min = min(start), cpg_max = max(end)), by = chrom]
profile_eligible_windows <- merge(eligible_windows, cpg_extents, by = "chrom", all = FALSE)
profile_eligible_windows <- profile_eligible_windows[end >= cpg_min & start <= cpg_max]
ranked_windows <- rbindlist(list(
  profile_eligible_windows[order(-pct_5hmc_of_valid_calls)][seq_len(min(top_window_count, .N)),
    .(category = "Highest 5hmC", chrom, start, end, pct_5mc_of_valid_calls,
      pct_5hmc_of_valid_calls, valid_calls, mean_depth)],
  profile_eligible_windows[order(pct_5mc_of_valid_calls)][seq_len(min(top_window_count, .N)),
    .(category = "Lowest 5mC", chrom, start, end, pct_5mc_of_valid_calls,
      pct_5hmc_of_valid_calls, valid_calls, mean_depth)],
  profile_eligible_windows[order(-pct_5mc_of_valid_calls)][seq_len(min(top_window_count, .N)),
    .(category = "Highest 5mC", chrom, start, end, pct_5mc_of_valid_calls,
      pct_5hmc_of_valid_calls, valid_calls, mean_depth)]
))
atomic_fwrite(ranked_windows, file.path(tables_dir, "extreme_methylation_windows.tsv"))
ranked_windows[, window_rank := seq_len(.N), by = category]

profile_windows <- ranked_windows[, head(.SD, 2L), by = category]
profile_windows[, region := paste0(as.character(chrom), ":", format(start, scientific = FALSE), "-",
                                   format(end, scientific = FALSE))]
profile_rows <- rbindlist(lapply(seq_len(nrow(profile_windows)), function(index) {
  region_row <- profile_windows[index]
  cpg[chrom == as.character(region_row$chrom) & start >= region_row$start & end <= region_row$end &
        valid_calls >= min_valid_coverage,
      .(category = region_row$category, window_rank = region_row$window_rank,
        region = region_row$region,
        position_kb = (start - region_row$start) / 1000,
        pct_5mc, pct_5hmc, valid_calls)]
}), use.names = TRUE, fill = TRUE)
if (nrow(profile_rows) > 0L) {
  profile_long <- melt(profile_rows,
    id.vars = c("category", "window_rank", "region", "position_kb", "valid_calls"),
    measure.vars = c("pct_5mc", "pct_5hmc"),
    variable.name = "modification", value.name = "percent")
  profile_long[, modification := factor(modification,
    levels = c("pct_5mc", "pct_5hmc"), labels = c("5mC", "5hmC"))]
  profile_long[, position_bin_kb := 2 * floor(position_kb / 2)]
  atomic_fwrite(profile_long, file.path(tables_dir, "extreme_window_profile_data.tsv.gz"), compress = TRUE)
  profile_trace <- profile_long[, .(
    percent = weighted.mean(percent, valid_calls),
    cpg_sites = .N,
    valid_calls = sum(valid_calls)
  ), by = .(category, window_rank, region, modification, position_bin_kb)]
  profile_trace[, panel := paste(category, region, sep = " | ")]
  p_profiles <- ggplot(profile_trace, aes(position_bin_kb, percent, color = modification)) +
    geom_line(linewidth = 0.8) +
    geom_point(aes(size = cpg_sites), alpha = 0.65) +
    facet_wrap(~panel, ncol = 2, scales = "free_x") +
    coord_cartesian(ylim = c(0, 100)) +
    scale_color_manual(values = modification_colors) +
    scale_size_continuous(range = c(0.5, 2.5)) +
    labs(
      title = "Representative extreme-window methylation profiles",
      subtitle = paste0("CpGs require at least ", min_valid_coverage,
                        " valid calls; coverage-weighted 2 kb traces; not DMRs"),
      x = "Position within window (kb)", y = "Modified calls (%)",
      color = NULL, size = "Measured CpGs"
    ) +
    theme(legend.position = "bottom", axis.text.x = element_text(angle = 45, hjust = 1),
          strip.text = element_text(size = 8))
  save_plot(p_profiles, "13_Extreme_Window_Regional_Profiles", 12, 9)
} else {
  stop("No CpGs were available for the extreme-window regional profiles")
}

# Provide comparable profiles across progressively less-extreme portions of each
# top-20 ranking. The window size, CpG coverage threshold, and 2 kb aggregation
# stay fixed so differences between figures reflect the selected rank band.
make_rank_band_profiles <- function(rank_start, rank_end, figure_stem) {
  selected_windows <- ranked_windows[window_rank >= rank_start & window_rank <= rank_end]
  selected_windows[, region := paste0(
    as.character(chrom), ":", format(start, scientific = FALSE), "-",
    format(end, scientific = FALSE)
  )]

  rank_profile_rows <- rbindlist(lapply(seq_len(nrow(selected_windows)), function(index) {
    region_row <- selected_windows[index]
    cpg[
      chrom == as.character(region_row$chrom) &
        start >= region_row$start & end <= region_row$end &
        valid_calls >= min_valid_coverage,
      .(
        category = as.character(region_row$category),
        window_rank = region_row$window_rank,
        region = region_row$region,
        position_kb = (start - region_row$start) / 1000,
        pct_5mc, pct_5hmc, valid_calls
      )
    ]
  }), use.names = TRUE, fill = TRUE)
  if (nrow(rank_profile_rows) == 0L) {
    stop("No CpGs were available for rank-band regional profiles: ", rank_start, "-", rank_end)
  }

  rank_profile_long <- melt(
    rank_profile_rows,
    id.vars = c("category", "window_rank", "region", "position_kb", "valid_calls"),
    measure.vars = c("pct_5mc", "pct_5hmc"),
    variable.name = "modification",
    value.name = "percent"
  )
  rank_profile_long[, modification := factor(
    modification,
    levels = c("pct_5mc", "pct_5hmc"),
    labels = c("5mC", "5hmC")
  )]
  rank_profile_long[, position_bin_kb := 2 * floor(position_kb / 2)]
  atomic_fwrite(
    rank_profile_long,
    file.path(tables_dir, paste0(figure_stem, "_plot_data.tsv.gz")),
    compress = TRUE
  )

  rank_profile_trace <- rank_profile_long[, .(
    percent = weighted.mean(percent, valid_calls),
    cpg_sites = .N,
    valid_calls = sum(valid_calls)
  ), by = .(category, window_rank, region, modification, position_bin_kb)]
  rank_profile_trace[, panel := paste0(
    category, " rank ", window_rank, " | ", region
  )]
  panel_levels <- unique(rank_profile_trace$panel)
  rank_profile_trace[, panel := factor(panel, levels = panel_levels)]

  rank_profile_plot <- ggplot(
    rank_profile_trace,
    aes(position_bin_kb, percent, color = modification)
  ) +
    geom_line(linewidth = 0.8) +
    geom_point(aes(size = cpg_sites), alpha = 0.65) +
    facet_wrap(~panel, ncol = 2, scales = "free_x") +
    coord_cartesian(ylim = c(0, 100)) +
    scale_color_manual(values = modification_colors) +
    scale_size_continuous(range = c(0.5, 2.5)) +
    labs(
      title = paste0("Regional methylation profiles: ranks ", rank_start, "-", rank_end),
      subtitle = paste0(
        "Ranked within highest 5hmC, lowest 5mC, and highest 5mC; ",
        "CpGs require at least ", min_valid_coverage,
        " valid calls; coverage-weighted 2 kb traces; not DMRs"
      ),
      x = "Position within window (kb)",
      y = "Modified calls (%)",
      color = NULL,
      size = "Measured CpGs"
    ) +
    theme(
      legend.position = "bottom",
      axis.text.x = element_text(angle = 45, hjust = 1),
      strip.text = element_text(size = 8)
    )
  save_plot(rank_profile_plot, figure_stem, 12, 9)
}

make_rank_band_profiles(3L, 4L, "13A_Regional_Profiles_Ranks_3_to_4")
make_rank_band_profiles(5L, 6L, "13B_Regional_Profiles_Ranks_5_to_6")
make_rank_band_profiles(7L, 8L, "13C_Regional_Profiles_Ranks_7_to_8")
make_rank_band_profiles(9L, 10L, "13D_Regional_Profiles_Ranks_9_to_10")

# -----------------------------------
# SixBase-compatible feature analysis
# -----------------------------------
feature_table_path <- file.path(tables_dir, "feature_region_methylation.tsv.gz")
feature_region_counts_path <- file.path(tables_dir, "feature_annotation_counts.tsv")

deduplicate_ranges <- function(ranges) {
  if (length(ranges) == 0L) return(ranges)
  keys <- paste0(seqnames(ranges), ":", start(ranges), "-", end(ranges), ":", strand(ranges))
  ranges[!duplicated(keys)]
}

metadata_or_na <- function(ranges, column) {
  if (column %in% colnames(mcols(ranges))) as.character(mcols(ranges)[[column]]) else rep(NA_character_, length(ranges))
}

aggregate_feature_ranges <- function(ranges, feature_type, cpg_ranges, cpg_table) {
  if (length(ranges) == 0L) {
    message("No annotation ranges for ", feature_type)
    return(data.table())
  }
  message("Overlapping CpGs with ", feature_type, " regions: ", format(length(ranges), big.mark = ","))
  hits <- findOverlaps(ranges, cpg_ranges, ignore.strand = TRUE)
  if (length(hits) == 0L) return(data.table())
  query_index <- queryHits(hits)
  subject_index <- subjectHits(hits)
  keep <- cpg_table$valid_calls[subject_index] >= min_valid_coverage
  query_index <- query_index[keep]
  subject_index <- subject_index[keep]
  if (length(query_index) == 0L) return(data.table())

  hit_table <- data.table(
    region_index = query_index,
    valid_calls = cpg_table$valid_calls[subject_index],
    modified_5mc_calls = cpg_table$modified_5mc_calls[subject_index],
    modified_5hmc_calls = cpg_table$modified_5hmc_calls[subject_index],
    canonical_calls = cpg_table$canonical_calls[subject_index],
    site_pct_5mc = cpg_table$pct_5mc[subject_index],
    site_pct_5hmc = cpg_table$pct_5hmc[subject_index]
  )
  summary <- hit_table[, .(
    measured_cpg_sites = .N,
    valid_calls = sum(valid_calls),
    modified_5mc_calls = sum(modified_5mc_calls),
    modified_5hmc_calls = sum(modified_5hmc_calls),
    canonical_calls = sum(canonical_calls),
    mean_valid_coverage = mean(valid_calls),
    mean_site_5mc_percent = mean(site_pct_5mc),
    mean_site_5hmc_percent = mean(site_pct_5hmc)
  ), by = region_index]
  summary[, `:=`(
    weighted_5mc_percent = 100 * modified_5mc_calls / valid_calls,
    weighted_5hmc_percent = 100 * modified_5hmc_calls / valid_calls,
    weighted_total_modified_percent = 100 * (modified_5mc_calls + modified_5hmc_calls) / valid_calls
  )]

  region_meta <- data.table(
    region_index = seq_along(ranges),
    feature_type = feature_type,
    feature_id = paste0(gsub("[^A-Za-z0-9]+", "_", feature_type), "_", seq_along(ranges)),
    chrom = as.character(seqnames(ranges)),
    start = start(ranges) - 1L,
    end = end(ranges),
    region_length = width(ranges),
    strand = as.character(strand(ranges)),
    gene_id = metadata_or_na(ranges, "gene_id"),
    gene_name = metadata_or_na(ranges, "gene_name"),
    gene_type = metadata_or_na(ranges, "gene_type")
  )
  result <- merge(region_meta, summary, by = "region_index", all = FALSE)
  result[, region_index := NULL]
  rm(hits, query_index, subject_index, keep, hit_table, summary, region_meta)
  invisible(gc())
  result
}

if (file.exists(feature_table_path) && file.info(feature_table_path)$size > 0 &&
    file.exists(feature_region_counts_path) && file.info(feature_region_counts_path)$size > 0) {
  message("Reusing completed feature-region methylation table")
  feature_methylation <- read_tsv(feature_table_path)
  feature_annotation_counts <- read_tsv(feature_region_counts_path)
} else {
  message("Loading GENCODE vM25 annotations used by SixBase")
  gff <- import(opt[["gff3"]])
  keep_seqlevels <- intersect(seqlevels(gff), chromosome_order)
  gff <- keepSeqlevels(gff, keep_seqlevels, pruning.mode = "coarse")
  known_lengths <- setNames(fai$length, fai$chrom)
  annotation_lengths <- known_lengths[as.character(seqnames(gff))]
  gff <- gff[is.na(annotation_lengths) | end(gff) <= annotation_lengths]
  seqlengths(gff)[names(seqlengths(gff)) %in% names(known_lengths)] <-
    known_lengths[names(seqlengths(gff))[names(seqlengths(gff)) %in% names(known_lengths)]]
  gff <- trim(gff)

  genes <- gff[gff$type == "gene"]
  protein_coding_exons <- gff[gff$type == "exon" & !is.na(gff$gene_type) &
                                gff$gene_type == "protein_coding"]
  five_prime_utrs <- gff[gff$type == "five_prime_UTR" & !is.na(gff$gene_type) &
                            gff$gene_type == "protein_coding" &
                            !is.na(gff$transcript_support_level) &
                            as.character(gff$transcript_support_level) == "1"]
  three_prime_utrs <- gff[gff$type == "three_prime_UTR" & !is.na(gff$gene_type) &
                             gff$gene_type == "protein_coding" &
                             !is.na(gff$transcript_support_level) &
                             as.character(gff$transcript_support_level) == "1"]

  promoters <- trim(flank(genes, width = 1000L, start = TRUE, both = FALSE))
  protein_coding_exons <- deduplicate_ranges(protein_coding_exons)
  five_prime_utrs <- deduplicate_ranges(five_prime_utrs)
  three_prime_utrs <- deduplicate_ranges(three_prime_utrs)

  message("Deriving protein-coding introns from transcript-ordered GENCODE exons")
  exon_table <- data.table(
    chrom = as.character(seqnames(protein_coding_exons)),
    exon_start = start(protein_coding_exons),
    exon_end = end(protein_coding_exons),
    strand = as.character(strand(protein_coding_exons)),
    transcript_id = as.character(protein_coding_exons$transcript_id),
    gene_id = as.character(protein_coding_exons$gene_id),
    gene_name = as.character(protein_coding_exons$gene_name),
    gene_type = as.character(protein_coding_exons$gene_type)
  )
  exon_table <- exon_table[!is.na(transcript_id) & transcript_id != ""]
  setorder(exon_table, transcript_id, exon_start, exon_end)
  exon_table[, `:=`(
    intron_start = exon_end + 1L,
    intron_end = data.table::shift(exon_start, type = "lead") - 1L
  ), by = transcript_id]
  intron_table <- exon_table[!is.na(intron_end) & intron_end >= intron_start]
  introns <- GRanges(
    intron_table$chrom,
    IRanges(intron_table$intron_start, intron_table$intron_end),
    strand = intron_table$strand,
    gene_id = intron_table$gene_id,
    gene_name = intron_table$gene_name,
    gene_type = intron_table$gene_type,
    transcript_id = intron_table$transcript_id
  )
  introns <- deduplicate_ranges(introns)
  rm(exon_table, intron_table)

  lnc_gene_types <- c(
    "lincRNA", "antisense", "sense_intronic", "sense_overlapping",
    "processed_transcript", "bidirectional_promoter_lncRNA",
    "3prime_overlapping_ncRNA", "macro_lncRNA", "non_coding"
  )
  lncrnas <- genes[genes$gene_type %in% lnc_gene_types]
  mirnas <- genes[!is.na(genes$gene_type) & genes$gene_type == "miRNA"]

  intergenic_table <- fread(opt[["intergenic"]], sep = "\t", header = FALSE,
                            select = 1:3, col.names = c("chrom", "start", "end"))
  intergenic_table <- intergenic_table[chrom %chin% chromosome_order & end > start]
  intergenic <- GRanges(intergenic_table$chrom, IRanges(intergenic_table$start + 1L, intergenic_table$end))

  ccre_table <- fread(opt[["ccre"]], sep = "\t", header = TRUE, check.names = FALSE)
  setnames(ccre_table, c("#chrom", "chromStart", "chromEnd"), c("chrom", "start", "end"))
  ccre_table <- ccre_table[chrom %chin% chromosome_order & end > start]
  ccres <- GRanges(ccre_table$chrom, IRanges(ccre_table$start + 1L, ccre_table$end))
  mcols(ccres)$ccre <- ccre_table$ccre

  island_json <- fromJSON(opt[["cpg-islands"]], simplifyDataFrame = TRUE)
  island_tables <- Filter(function(x) is.data.frame(x) && nrow(x) > 0L, island_json$cpgIslandExt)
  island_table <- rbindlist(island_tables, fill = TRUE)
  island_table <- island_table[chrom %chin% chromosome_order & chromEnd > chromStart]
  cpg_islands <- GRanges(island_table$chrom, IRanges(island_table$chromStart + 1L, island_table$chromEnd))

  make_flanks <- function(ranges, near_start, near_end) {
    starts <- pmax(1L, start(ranges) - near_end)
    ends <- pmax(0L, start(ranges) - near_start - 1L)
    left <- ranges[ends >= starts]
    ranges(left) <- IRanges(starts[ends >= starts], ends[ends >= starts])
    right_starts <- end(ranges) + near_start + 1L
    right_ends <- pmin(known_lengths[as.character(seqnames(ranges))], end(ranges) + near_end)
    right <- ranges[right_ends >= right_starts]
    ranges(right) <- IRanges(right_starts[right_ends >= right_starts], right_ends[right_ends >= right_starts])
    c(left, right)
  }
  cpg_shores <- make_flanks(cpg_islands, 0L, 2000L)
  cpg_shelves <- make_flanks(cpg_islands, 2000L, 4000L)

  feature_ranges <- list(
    "Gene" = genes,
    "Promoter" = promoters,
    "5' UTR" = five_prime_utrs,
    "Exon" = protein_coding_exons,
    "Intron" = introns,
    "3' UTR" = three_prime_utrs,
    "Intergenic" = intergenic,
    "CpG island" = cpg_islands,
    "CpG shore" = cpg_shores,
    "CpG shelf" = cpg_shelves,
    "cCRE" = ccres,
    "miRNA" = mirnas,
    "lncRNA" = lncrnas
  )
  feature_annotation_counts <- rbindlist(lapply(names(feature_ranges), function(type) {
    data.table(feature_type = type, annotated_regions = length(feature_ranges[[type]]))
  }))
  atomic_fwrite(feature_annotation_counts, feature_region_counts_path)

  cpg_for_features <- cpg[is_main_chromosome(chrom)]
  cpg_ranges <- GRanges(
    cpg_for_features$chrom,
    IRanges(cpg_for_features$start + 1L, cpg_for_features$end)
  )
  feature_methylation <- rbindlist(lapply(names(feature_ranges), function(type) {
    aggregate_feature_ranges(feature_ranges[[type]], type, cpg_ranges, cpg_for_features)
  }), use.names = TRUE, fill = TRUE)
  if (nrow(feature_methylation) == 0L) stop("Feature aggregation produced no measured regions")
  atomic_fwrite(feature_methylation, feature_table_path, compress = TRUE)
  rm(gff, genes, protein_coding_exons, five_prime_utrs, three_prime_utrs,
     promoters, introns, lncrnas, mirnas, intergenic, ccres, cpg_islands,
     cpg_shores, cpg_shelves, feature_ranges, cpg_ranges, cpg_for_features)
  invisible(gc())
}

feature_summary <- feature_methylation[, .(
  measured_regions = .N,
  regions_passing_plot_cpg_minimum = sum(measured_cpg_sites >= min_feature_cpgs),
  measured_cpg_sites = sum(measured_cpg_sites),
  valid_calls = sum(valid_calls),
  modified_5mc_calls = sum(modified_5mc_calls),
  modified_5hmc_calls = sum(modified_5hmc_calls),
  weighted_5mc_percent = 100 * sum(modified_5mc_calls) / sum(valid_calls),
  weighted_5hmc_percent = 100 * sum(modified_5hmc_calls) / sum(valid_calls),
  median_region_5mc_percent = median(weighted_5mc_percent, na.rm = TRUE),
  median_region_5hmc_percent = median(weighted_5hmc_percent, na.rm = TRUE),
  median_valid_coverage = median(mean_valid_coverage, na.rm = TRUE)
), by = feature_type]
feature_summary <- merge(feature_annotation_counts, feature_summary, by = "feature_type", all.x = TRUE)
atomic_fwrite(feature_summary, file.path(tables_dir, "feature_methylation_summary.tsv"))

feature_plot_types <- c(
  "Gene", "Promoter", "5' UTR", "Exon", "Intron", "3' UTR",
  "Intergenic", "CpG island", "cCRE", "miRNA", "lncRNA"
)
feature_plot <- feature_methylation[
  feature_type %chin% feature_plot_types & measured_cpg_sites >= min_feature_cpgs
]
feature_plot[, feature_type := factor(feature_type, levels = feature_plot_types)]
if (nrow(feature_plot) == 0L) stop("No feature regions passed the plotting minimum")

p_feature_5mc <- ggplot(feature_plot, aes(feature_type, weighted_5mc_percent, fill = feature_type)) +
  geom_boxplot(outlier.shape = NA, width = 0.72) +
  coord_cartesian(ylim = c(0, 100)) +
  scale_fill_viridis_d(option = "C", guide = "none") +
  theme(axis.text.x = element_text(angle = 35, hjust = 1)) +
  labs(
    title = "5mC across genomic feature regions",
    subtitle = paste0("Coverage-weighted regions with at least ", min_feature_cpgs,
                      " CpGs at ", min_valid_coverage, "x valid-call depth"),
    x = NULL, y = "Region-level 5mC (% of valid calls)"
  )
save_plot(p_feature_5mc, "14_Feature_Methylation_5mC_Boxplot", 12, 6.5)

p_feature_5hmc <- ggplot(feature_plot, aes(feature_type, weighted_5hmc_percent, fill = feature_type)) +
  geom_boxplot(outlier.shape = NA, width = 0.72) +
  scale_y_continuous(
    breaks = seq(0, 6, by = 1),
    expand = expansion(mult = c(0.02, 0.04))
  ) +
  coord_cartesian(ylim = c(0, 6), expand = TRUE) +
  scale_fill_viridis_d(option = "C", guide = "none") +
  theme(axis.text.x = element_text(angle = 35, hjust = 1)) +
  labs(
    title = "5hmC across genomic feature regions",
    subtitle = "SixBase-compatible feature-distribution view; y-axis shown through 6%",
    x = NULL, y = "Region-level 5hmC (% of valid calls)"
  )
save_plot(p_feature_5hmc, "15_Feature_Methylation_5hmC_Boxplot", 12, 6.5)

hmc_zoom_max <- max(0.5, quantile(feature_plot$weighted_5hmc_percent, 0.95, na.rm = TRUE))
p_feature_5hmc_zoom <- p_feature_5hmc +
  coord_cartesian(ylim = c(0, hmc_zoom_max)) +
  labs(title = "5hmC across genomic feature regions (zoomed)",
       subtitle = "Y-axis ends at the 95th percentile to reveal low-level structure")
save_plot(p_feature_5hmc_zoom, "16_Feature_Methylation_5hmC_Boxplot_Zoom", 12, 6.5)

cpg_context_types <- c("CpG island", "CpG shore", "CpG shelf")
cpg_context_plot <- feature_methylation[
  feature_type %chin% cpg_context_types & measured_cpg_sites >= min_feature_cpgs
]
cpg_context_plot[, feature_type := factor(feature_type, levels = cpg_context_types)]
coverage_zoom <- quantile(cpg_context_plot$mean_valid_coverage, 0.99, na.rm = TRUE)
p_feature_coverage <- ggplot(cpg_context_plot, aes(feature_type, mean_valid_coverage, fill = feature_type)) +
  geom_violin(scale = "width", trim = TRUE) +
  geom_boxplot(width = 0.14, outlier.shape = NA, fill = "white") +
  coord_cartesian(ylim = c(0, coverage_zoom)) +
  scale_fill_manual(values = c("CpG island" = "#4C78A8", "CpG shore" = "#F58518",
                               "CpG shelf" = "#54A24B"), guide = "none") +
  labs(
    title = "Valid-call coverage in CpG islands, shores, and shelves",
    subtitle = "Coverage violin reproduced from the SixBase genomic-feature workflow",
    x = NULL, y = "Mean valid calls per measured CpG"
  )
save_plot(p_feature_coverage, "17_CpG_Feature_Coverage_Violin", 9, 6.5)

set.seed(42)
length_plot_data <- cpg_context_plot
if (nrow(length_plot_data) > 30000L) {
  sampled_rows <- length_plot_data[, .(row_index = sample(.I, min(.N, 10000L))),
                                   by = feature_type]$row_index
  length_plot_data <- length_plot_data[sampled_rows]
}
atomic_fwrite(length_plot_data[, .(feature_type, region_length, measured_cpg_sites,
                                    mean_valid_coverage)],
              file.path(tables_dir, "cpg_feature_length_plot_data.tsv.gz"), compress = TRUE)
p_length <- ggplot(length_plot_data, aes(region_length, measured_cpg_sites, color = feature_type)) +
  geom_point(alpha = 0.25, size = 0.7) +
  geom_smooth(method = "lm", se = FALSE, linewidth = 0.8) +
  facet_wrap(~feature_type, scales = "free") +
  scale_x_log10(labels = label_number(big.mark = ",")) +
  scale_y_log10(labels = label_number(big.mark = ",")) +
  scale_color_manual(values = c("CpG island" = "#4C78A8", "CpG shore" = "#F58518",
                                "CpG shelf" = "#54A24B"), guide = "none") +
  labs(
    title = "CpG feature length versus measured CpG count",
    subtitle = "SixBase-compatible feature length relationship",
    x = "Feature length (bp, log scale)", y = "Measured CpGs (log scale)"
  )
save_plot(p_length, "18_CpG_Feature_Length_vs_Measured_CpGs", 11, 6.5)

feature_summary_plot <- melt(
  feature_summary[feature_type %chin% feature_plot_types],
  id.vars = "feature_type",
  measure.vars = c("weighted_5mc_percent", "weighted_5hmc_percent"),
  variable.name = "modification", value.name = "percent"
)
feature_summary_plot[, `:=`(
  feature_type = factor(feature_type, levels = feature_plot_types),
  modification = factor(modification,
    levels = c("weighted_5mc_percent", "weighted_5hmc_percent"), labels = c("5mC", "5hmC"))
)]
p_feature_summary <- ggplot(feature_summary_plot, aes(feature_type, percent, fill = modification)) +
  geom_col(position = "dodge") +
  scale_fill_manual(values = modification_colors) +
  theme(axis.text.x = element_text(angle = 35, hjust = 1), legend.position = "bottom") +
  labs(
    title = "Coverage-weighted methylation by genomic feature class",
    subtitle = "Counts are summed before percentages are calculated",
    x = NULL, y = "Modified calls (%)", fill = NULL
  )
save_plot(p_feature_summary, "19_Feature_Weighted_Methylation_Summary", 12, 6.5)

top_feature_regions <- rbindlist(lapply(feature_plot_types, function(type) {
  eligible <- feature_methylation[
    feature_type == type & measured_cpg_sites >= min_feature_cpgs
  ]
  if (nrow(eligible) == 0L) return(data.table())
  highest_hmc <- head(eligible[order(-weighted_5hmc_percent)], 20L)
  highest_hmc[, ranking := "Highest 5hmC"]
  lowest_mc <- head(eligible[order(weighted_5mc_percent)], 20L)
  lowest_mc[, ranking := "Lowest 5mC"]
  rbindlist(list(highest_hmc, lowest_mc), use.names = TRUE, fill = TRUE)
}), use.names = TRUE, fill = TRUE)
atomic_fwrite(top_feature_regions, file.path(tables_dir, "top_feature_regions.tsv"))

# Document how the SixBase figure families were transferred to this one-sample analysis.
sixbase_mapping <- data.table(
  sixbase_figure_family = c(
    "Global modification composition", "Global 5mC/5hmC percentage",
    "CG coverage distribution", "CG coverage thresholds",
    "Feature coverage violin", "Feature length versus CG count",
    "Feature methylation boxplots",
    "Regional methylation traces", "Manhattan plot",
    "Sample correlation matrices", "Sample correlation scatter plots",
    "PCA and scree plots", "DMR statistical scatter plots",
    "DMR heatmaps", "GO/KEGG and feature enrichment"
  ),
  stage05_status = c(
    rep("Directly reproduced", 7L),
    "Single-sample descriptive analogue", "Single-sample descriptive analogue",
    rep("Not scientifically available", 6L)
  ),
  stage05_output = c(
    "01_Global_CpG_Modification_Composition", "02_Global_CpG_Methylation_Levels",
    "03_CpG_Valid_Coverage_Distribution", "04_CpG_Coverage_Thresholds",
    "17_CpG_Feature_Coverage_Violin", "18_CpG_Feature_Length_vs_Measured_CpGs",
    "14-16_Feature_Methylation_Boxplots",
    "13_Extreme_Window_Regional_Profiles", "09-10_Genomewide_100kb_Windows",
    rep("NA", 6L)
  ),
  rationale = c(
    rep("The same quantity is available from one ONT sample.", 7L),
    "Extreme windows can be visualized, but cannot be called differential.",
    "Window methylation can be placed along chromosomes, but no p-values exist.",
    "Requires at least two samples.", "Requires at least two samples.",
    "Requires multiple samples.", "Requires biological groups and replication.",
    "Requires multiple samples or groups and a selected region set.",
    "Requires a statistically selected gene or feature set."
  )
)
atomic_fwrite(sixbase_mapping, file.path(tables_dir, "sixbase_figure_mapping.tsv"))

capture.output(sessionInfo(), file = file.path(output_dir, "R_session_info.txt"))

genome_coverage <- call_coverage[scope == "genome"][1L]
report_lines <- c(
  "ONT methylation exploration and visualization report",
  paste0("Sample: ", sample_id),
  paste0("Reference: ", reference_name),
  paste0("Generated: ", format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z")),
  "",
  "Headline CpG results",
  sprintf("  Covered CpG sites: %s of %s reference CpGs (%.6f%%)",
          format(genome_coverage$cpg_sites_with_valid_calls, big.mark = ",", scientific = FALSE),
          format(genome_coverage$reference_cpg_sites, big.mark = ",", scientific = FALSE),
          genome_coverage$pct_reference_cpg_sites_with_valid_calls),
  sprintf("  Global 5mC: %.6f%% of valid CpG calls",
          global_levels[category == "5mC", percent_of_valid_calls]),
  sprintf("  Global 5hmC: %.6f%% of valid CpG calls",
          global_levels[category == "5hmC", percent_of_valid_calls]),
  sprintf("  Total modified: %.6f%% of valid CpG calls",
          global_levels[category == "total_modified", percent_of_valid_calls]),
  sprintf("  Mean valid calls per represented CpG: %.4f", mean(cpg$valid_calls)),
  sprintf("  CpGs at the 60,000-observation safety cap: %s",
          format(nrow(high_depth_sites), big.mark = ",")),
  "",
  "Feature analysis",
  paste0("  Feature CpGs require at least ", min_valid_coverage, " valid calls."),
  paste0("  Boxplots require at least ", min_feature_cpgs, " measured CpGs per feature region."),
  "  Region percentages are coverage-weighted: summed modified calls / summed valid calls.",
  paste0("  GENCODE source: ", opt[["gff3"]]),
  paste0("  CpG-island source: ", opt[["cpg-islands"]]),
  paste0("  cCRE source: ", opt[["ccre"]]),
  paste0("  Intergenic source: ", opt[["intergenic"]]),
  "",
  "Interpretation boundaries",
  "  This is a single-sample descriptive analysis. It does not produce correlations,",
  "  PCA, differential methylation, statistical Manhattan plots, DMR heatmaps, or",
  "  enrichment tests. Those require additional samples, biological groups, and",
  "  appropriate replication. The extreme windows are candidates for review,",
  "  not DMRs. Sequencing depth and valid modification-call depth remain distinct.",
  "",
  "Output guide",
  "  figures/: PDF versions of every visualization (PNG export is disabled by default).",
  "  tables/: exact plot data, feature summaries, candidate windows, and provenance mapping.",
  "  sixbase_figure_mapping.tsv: direct, adapted, and unavailable SixBase figure families."
)
writeLines(report_lines, file.path(output_dir, "methylation_exploration_report.txt"))

# Build a dependency-free HTML dashboard that consolidates run provenance,
# alignment QC, sequencing coverage, modification-call QC, methylation results,
# and every Stage 05 visualization. Figures remain the canonical PDF files and
# are embedded by relative path so the report and its output directory can move
# together without duplicating large raster images.
html_escape <- function(value) {
  value <- as.character(value)
  value <- gsub("&", "&amp;", value, fixed = TRUE)
  value <- gsub("<", "&lt;", value, fixed = TRUE)
  value <- gsub(">", "&gt;", value, fixed = TRUE)
  value <- gsub('"', "&quot;", value, fixed = TRUE)
  gsub("'", "&#39;", value, fixed = TRUE)
}

format_integer <- function(value) {
  if (length(value) == 0L || is.na(value)) return("NA")
  format(as.numeric(value), big.mark = ",", scientific = FALSE, trim = TRUE)
}

format_percent <- function(value, digits = 2L) {
  if (length(value) == 0L || is.na(value)) return("NA")
  paste0(formatC(as.numeric(value), format = "f", digits = digits), "%")
}

stats_lines <- readLines(opt[["alignment-stats"]], n = 100L, warn = FALSE)
stats_lines <- stats_lines[startsWith(stats_lines, "SN\t")]
stats_fields <- strsplit(stats_lines, "\t", fixed = TRUE)
stats_names <- vapply(stats_fields, function(x) sub(":$", "", x[[2L]]), character(1))
stats_values <- vapply(stats_fields, function(x) x[[3L]], character(1))
alignment_metrics <- setNames(stats_values, stats_names)
alignment_value <- function(name) unname(alignment_metrics[[name]] %||% NA_character_)

coverage_metrics <- setNames(as.character(coverage_summary$value), coverage_summary$metric)
coverage_value <- function(name) unname(coverage_metrics[[name]] %||% NA_character_)

primary_reads <- as.numeric(alignment_value("raw total sequences"))
primary_mapped <- as.numeric(alignment_value("reads mapped"))
mapping_percent <- if (is.finite(primary_reads) && primary_reads > 0) {
  100 * primary_mapped / primary_reads
} else {
  NA_real_
}

card <- function(label, value, note = "") {
  paste0(
    '<div class="metric"><div class="metric-label">', html_escape(label),
    '</div><div class="metric-value">', html_escape(value), '</div>',
    if (nzchar(note)) paste0('<div class="metric-note">', html_escape(note), '</div>') else "",
    '</div>'
  )
}

cards <- c(
  card("Primary reads", format_integer(primary_reads), "Pass-read alignment input"),
  card("Primary mapped", format_percent(mapping_percent), format_integer(primary_mapped)),
  card("Mean read length", paste0(format_integer(alignment_value("average length")), " bp"),
       paste0("maximum ", format_integer(alignment_value("maximum length")), " bp")),
  card("Alignment error rate", format_percent(100 * as.numeric(alignment_value("error rate")), 2L),
       "Samtools mismatch estimate"),
  card("Mean sequencing depth", paste0(formatC(as.numeric(coverage_value("mean_depth")), format = "f", digits = 2L), "x"),
       "Mosdepth, MAPQ >= 0"),
  card("Genome covered >=1x", format_percent(coverage_value("pct_ge_1x"), 2L),
       paste0(format_integer(coverage_value("zero_coverage_bases")), " bases at 0x")),
  card("Genome covered >=10x", format_percent(coverage_value("pct_ge_10x"), 2L),
       paste0("20x: ", format_percent(coverage_value("pct_ge_20x"), 2L))),
  card("CpG sites represented", format_percent(genome_coverage$pct_reference_cpg_sites_with_valid_calls, 2L),
       paste0(format_integer(genome_coverage$cpg_sites_with_valid_calls), " sites")),
  card("Valid modification calls", format_percent(genome_coverage$pct_valid_calls_of_observations, 2L),
       paste0(format_integer(genome_coverage$valid_calls), " calls")),
  card("Global 5mC", format_percent(global_levels[category == "5mC", percent_of_valid_calls], 2L),
       paste0(format_integer(global_levels[category == "5mC", call_count]), " calls")),
  card("Global 5hmC", format_percent(global_levels[category == "5hmC", percent_of_valid_calls], 2L),
       paste0(format_integer(global_levels[category == "5hmC", call_count]), " calls")),
  card("Total modified", format_percent(global_levels[category == "total_modified", percent_of_valid_calls], 2L),
       "Coverage-weighted")
)

coverage_rows <- c("1", "5", "10", "20")
coverage_table_rows <- vapply(coverage_rows, function(threshold) {
  paste0(
    "<tr><td>&ge;", threshold, "x</td><td>",
    html_escape(format_integer(coverage_value(paste0("bases_ge_", threshold, "x")))),
    "</td><td>",
    html_escape(format_percent(coverage_value(paste0("pct_ge_", threshold, "x")), 3L)),
    "</td></tr>"
  )
}, character(1))

call_rows <- list(
  c("Reference CpG sites", format_integer(genome_coverage$reference_cpg_sites)),
  c("CpG sites with valid calls", format_integer(genome_coverage$cpg_sites_with_valid_calls)),
  c("Valid calls", format_integer(genome_coverage$valid_calls)),
  c("Failed/filtered calls", format_integer(genome_coverage$failed_filtered_calls)),
  c("No-call observations", format_integer(genome_coverage$no_call_calls)),
  c("Deletion observations", format_integer(genome_coverage$deletion_calls)),
  c("Different-base observations", format_integer(genome_coverage$different_base_calls)),
  c("Sites at high-depth safety cap", format_integer(nrow(high_depth_sites)))
)
call_table_rows <- vapply(call_rows, function(row) {
  paste0("<tr><td>", html_escape(row[[1L]]), "</td><td>", html_escape(row[[2L]]), "</td></tr>")
}, character(1))

figure_files <- sort(list.files(figures_dir, pattern = "[.]pdf$"))
figure_panels <- vapply(figure_files, function(filename) {
  title <- sub("^[0-9]+_", "", sub("[.]pdf$", "", filename))
  title <- gsub("_", " ", title, fixed = TRUE)
  path <- paste0("figures/", filename)
  paste0(
    '<article class="figure"><h3>', html_escape(title), '</h3>',
    '<object data="', html_escape(path), '" type="application/pdf" loading="lazy">',
    '<p>PDF preview is unavailable in this browser. <a href="', html_escape(path),
    '">Open the figure</a>.</p></object><p><a href="', html_escape(path),
    '">Open full-size PDF</a></p></article>'
  )
}, character(1))

table_files <- sort(list.files(tables_dir))
table_links <- vapply(table_files, function(filename) {
  paste0('<li><a href="tables/', html_escape(filename), '">', html_escape(filename), '</a></li>')
}, character(1))

flagstat_text <- paste(readLines(opt[["alignment-flagstat"]], warn = FALSE), collapse = "\n")
stage02_text <- paste(readLines(opt[["stage02-summary"]], warn = FALSE), collapse = "\n")
instrument_report_uri <- paste0("file://", normalizePath(opt[["instrument-report"]], mustWork = TRUE))

html_lines <- c(
  "<!DOCTYPE html>", '<html lang="en"><head><meta charset="utf-8">',
  '<meta name="viewport" content="width=device-width, initial-scale=1">',
  "<title>ONT sequencing and methylation QC report</title>",
  "<style>",
  ":root{--navy:#12304a;--blue:#2c7fb8;--orange:#f28e2b;--ink:#17212b;--muted:#5d6b78;--line:#dce4ea;--panel:#fff;--bg:#f4f7f9}",
  "*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font-family:Arial,Helvetica,sans-serif;line-height:1.5}",
  "header{background:linear-gradient(120deg,var(--navy),#245d78);color:white;padding:2.5rem max(1.5rem,calc((100% - 1200px)/2))}",
  "header h1{margin:0 0 .35rem;font-size:2rem}header p{margin:.2rem 0;color:#dcecf5}",
  "nav{position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid var(--line);padding:.7rem max(1rem,calc((100% - 1200px)/2));display:flex;gap:1rem;overflow:auto}",
  "nav a{color:var(--navy);font-weight:700;text-decoration:none;white-space:nowrap}main{max-width:1200px;margin:auto;padding:1.5rem}",
  "section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:1.4rem;margin-bottom:1.4rem;box-shadow:0 2px 8px #12304a0a}",
  "h2{color:var(--navy);border-bottom:2px solid #eaf0f4;padding-bottom:.45rem}h3{color:var(--navy)}",
  ".metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:.9rem}.metric{border-left:5px solid var(--blue);background:#f8fbfd;padding:1rem;border-radius:7px}",
  ".metric-label{font-size:.82rem;color:var(--muted);text-transform:uppercase;font-weight:700}.metric-value{font-size:1.65rem;font-weight:700;color:var(--navy)}.metric-note{font-size:.82rem;color:var(--muted)}",
  ".notice{border-left:5px solid var(--orange);background:#fff8ed;padding:1rem;border-radius:7px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:1rem}",
  "table{border-collapse:collapse;width:100%}th,td{padding:.55rem;border-bottom:1px solid var(--line);text-align:left}th{background:#edf3f7}",
  ".figures{display:grid;grid-template-columns:repeat(auto-fit,minmax(480px,1fr));gap:1.2rem}.figure{border:1px solid var(--line);border-radius:8px;padding:1rem}.figure object{width:100%;height:610px;border:1px solid var(--line)}",
  "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#182733;color:#edf5f8;padding:1rem;border-radius:6px;max-height:32rem;overflow:auto}a{color:#176b96}footer{text-align:center;color:var(--muted);padding:1rem}",
  "@media(max-width:650px){.figures{grid-template-columns:1fr}.figure object{height:470px}header h1{font-size:1.55rem}}",
  "</style></head><body>",
  "<header><h1>ONT sequencing and methylation QC report</h1>",
  paste0("<p><strong>Sample:</strong> ", html_escape(sample_id), " &nbsp; <strong>Reference:</strong> ", html_escape(reference_name), "</p>"),
  paste0("<p>Generated ", html_escape(format(Sys.time(), "%Y-%m-%d %H:%M:%S %z")), "</p></header>"),
  '<nav><a href="#summary">Summary</a><a href="#alignment">Alignment</a><a href="#coverage">Coverage</a><a href="#modification">Modification QC</a><a href="#figures">Figures</a><a href="#data">Data</a><a href="#scope">Scope</a></nav><main>',
  '<section id="summary"><h2>QC summary</h2><div class="metrics">', cards, "</div></section>",
  '<section id="alignment"><h2>Alignment and read QC</h2><div class="grid"><div><h3>Key alignment statistics</h3><table><tbody>',
  paste0("<tr><td>Primary reads</td><td>", html_escape(format_integer(primary_reads)), "</td></tr>"),
  paste0("<tr><td>Primary mapped reads</td><td>", html_escape(format_integer(primary_mapped)), " (", html_escape(format_percent(mapping_percent, 3L)), ")</td></tr>"),
  paste0("<tr><td>Secondary alignments</td><td>", html_escape(format_integer(alignment_value("non-primary alignments"))), "</td></tr>"),
  paste0("<tr><td>Supplementary alignments</td><td>", html_escape(format_integer(alignment_value("supplementary alignments"))), "</td></tr>"),
  paste0("<tr><td>Mapped bases (CIGAR)</td><td>", html_escape(format_integer(alignment_value("bases mapped (cigar)"))), "</td></tr>"),
  paste0("<tr><td>Mean aligned-read length</td><td>", html_escape(format_integer(alignment_value("average length"))), " bp</td></tr>"),
  paste0("<tr><td>Maximum aligned-read length</td><td>", html_escape(format_integer(alignment_value("maximum length"))), " bp</td></tr>"),
  paste0("<tr><td>Mean SAM base quality</td><td>", html_escape(alignment_value("average quality")), "</td></tr>"),
  "</tbody></table></div><div><h3>Original instrument report</h3>",
  "<p>The MinKNOW report covers acquisition, channel activity, yield over time, pass/fail reads, read-length distributions, and basecall-quality distributions.</p>",
  paste0('<p><a href="', html_escape(instrument_report_uri), '"><strong>Open the original ONT run report</strong></a></p>'),
  '<p class="notice">The analysis pipeline intentionally starts from the 74 pass modBAMs because they retain MM/ML/MN modification tags. Instrument-wide pass/fail metrics therefore remain in the immutable MinKNOW report.</p></div></div>',
  "<details><summary>Complete Samtools flagstat</summary><pre>", html_escape(flagstat_text), "</pre></details>",
  "<details><summary>Stage 02 alignment provenance</summary><pre>", html_escape(stage02_text), "</pre></details></section>",
  '<section id="coverage"><h2>Genome coverage QC</h2><div class="grid"><div><table><thead><tr><th>Depth threshold</th><th>Bases</th><th>Reference</th></tr></thead><tbody>',
  coverage_table_rows, "</tbody></table></div><div><table><tbody>",
  paste0("<tr><td>Reference bases</td><td>", html_escape(format_integer(coverage_value("reference_bases"))), "</td></tr>"),
  paste0("<tr><td>Mean depth</td><td>", html_escape(formatC(as.numeric(coverage_value("mean_depth")), format = "f", digits = 3L)), "x</td></tr>"),
  paste0("<tr><td>Zero-coverage intervals</td><td>", html_escape(format_integer(coverage_value("zero_coverage_interval_count"))), "</td></tr>"),
  paste0("<tr><td>Low-depth intervals (1–4x)</td><td>", html_escape(format_integer(coverage_value("low_depth_interval_count"))), "</td></tr>"),
  paste0("<tr><td>Zero-coverage configured windows</td><td>", html_escape(format_integer(coverage_value("zero_coverage_window_count"))), "</td></tr>"),
  "</tbody></table></div></div><p>Sequencing depth excludes unmapped, secondary, QC-fail, and duplicate records (SAM flag mask 1796); supplementary alignments are included. Sequencing depth is distinct from valid modification-call depth.</p></section>",
  '<section id="modification"><h2>Modification-call and methylation QC</h2><div class="grid"><div><table><tbody>', call_table_rows,
  "</tbody></table></div><div><h3>Method</h3><p>CpG dyads are strand-combined while 5mC and 5hmC remain separate. Percentages are coverage-weighted from validated call counts. The lowest probability decile is classified as failed/filtered, and localized extreme depth is capped at 60,000 observations to avoid counter saturation.</p>",
  paste0("<p><strong>Canonical C:</strong> ", html_escape(format_percent(global_levels[category == "canonical_C", percent_of_valid_calls], 3L)), "<br><strong>5mC:</strong> ", html_escape(format_percent(global_levels[category == "5mC", percent_of_valid_calls], 3L)), "<br><strong>5hmC:</strong> ", html_escape(format_percent(global_levels[category == "5hmC", percent_of_valid_calls], 3L)), "</p></div></div></section>"),
  '<section id="figures"><h2>QC and methylation visualizations</h2><p>Each browser preview uses the canonical publication-quality PDF produced by Stage 05.</p><div class="figures">',
  figure_panels, "</div></section>",
  '<section id="data"><h2>Supporting data and provenance</h2><div class="grid"><div><h3>Exact plot-data tables</h3><ul>', table_links,
  '</ul></div><div><h3>Reports</h3><ul><li><a href="methylation_exploration_report.txt">Plain-text interpretation report</a></li><li><a href="R_session_info.txt">R session information</a></li>',
  paste0('<li><a href="', html_escape(instrument_report_uri), '">Original ONT instrument report</a></li></ul>'),
  "<p>Stage-specific checksums, tool versions, settings, inputs, and output sizes are recorded in the Stage 03, 04, and 05 manifests.</p></div></div></section>",
  '<section id="scope"><h2>Interpretation scope</h2><div class="notice"><strong>Single-sample descriptive analysis.</strong> This report does not provide sample correlation, PCA, differential methylation, statistical Manhattan plots, DMR/DhMR calls, differential heatmaps, or enrichment. Those require biological groups and appropriate replication. Extreme windows are review candidates, not DMRs.</div></section>',
  "</main><footer>Generated by ONTAnalysis Stage 05</footer></body></html>"
)
writeLines(html_lines, file.path(output_dir, "ont_methylation_qc_report.html"), useBytes = TRUE)

message("Stage 05 R analysis complete")
