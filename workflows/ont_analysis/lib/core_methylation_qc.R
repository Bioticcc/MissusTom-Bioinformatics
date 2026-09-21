#!/usr/bin/env Rscript
# Annotation-free Stage 05: retain descriptive sequencing-QC and methylation figures.
suppressPackageStartupMessages({ library(data.table); library(ggplot2) })

args <- commandArgs(trailingOnly = TRUE)
if (length(args) %% 2L != 0L || any(!startsWith(args[seq(1L, length(args), 2L)], "--"))) {
  stop("Stage 05 core options must be --key value pairs")
}
opt <- as.list(setNames(args[seq(2L, length(args), 2L)], sub("^--", "", args[seq(1L, length(args), 2L)])))
need <- c("sample-id", "reference-name", "global-levels", "chromosome-methylation", "chromosome-coverage", "coverage-summary", "output-dir")
if (length(setdiff(need, names(opt)))) stop("Missing Stage 05 core option")
for (key in need[3:6]) if (!file.exists(opt[[key]]) || file.info(opt[[key]])$size <= 0) stop("Missing core input: ", key)

out <- normalizePath(opt[["output-dir"]], mustWork = FALSE)
figs <- file.path(out, "figures"); tabs <- file.path(out, "tables")
dir.create(figs, recursive = TRUE, showWarnings = FALSE); dir.create(tabs, recursive = TRUE, showWarnings = FALSE)
global <- fread(opt[["global-levels"]]); chrom <- fread(opt[["chromosome-methylation"]])
coverage <- fread(opt[["chromosome-coverage"]]); coverage_summary <- fread(opt[["coverage-summary"]])
required_global <- c("category", "percent_of_valid_calls")
if (length(setdiff(required_global, names(global)))) stop("Global methylation summary has unexpected columns")
if (!all(c("chrom", "percent_5mc") %in% names(chrom))) stop("Chromosome methylation summary has unexpected columns")
if (!all(c("chrom", "mean_depth") %in% names(coverage))) stop("Chromosome coverage summary has unexpected columns")
fwrite(global, file.path(tabs, "global_methylation_plot_data.tsv"), sep = "\t")
fwrite(chrom, file.path(tabs, "chromosome_methylation_plot_data.tsv"), sep = "\t")
fwrite(coverage, file.path(tabs, "chromosome_coverage_plot_data.tsv"), sep = "\t")
fwrite(coverage_summary, file.path(tabs, "coverage_summary_plot_data.tsv"), sep = "\t")

save <- function(plot, name, width = 9, height = 6) {
  ggsave(file.path(figs, paste0(name, ".pdf")), plot, width = width, height = height, device = cairo_pdf, bg = "white")
}
base_theme <- theme_bw() + theme(axis.text.x = element_text(angle = 45, hjust = 1))
save(ggplot(global[category %in% c("canonical_C", "5mC", "5hmC")], aes(category, percent_of_valid_calls, fill = category)) + geom_col() + base_theme + labs(title = "Global CpG modification composition", x = NULL, y = "Percent of valid CpG calls"), "01_Global_CpG_Modification_Composition")
save(ggplot(global[category %in% c("5mC", "5hmC", "total_modified")], aes(category, percent_of_valid_calls, fill = category)) + geom_col() + base_theme + labs(title = "Global CpG methylation levels", x = NULL, y = "Percent of valid CpG calls"), "02_Global_CpG_Methylation_Levels")
save(ggplot(chrom, aes(chrom, percent_5mc)) + geom_col(fill = "#2C7FB8") + base_theme + labs(title = "Chromosome CpG 5mC levels", x = "Chromosome", y = "Percent of valid CpG calls"), "06_Chromosome_CpG_Methylation_Levels", 11, 6)
save(ggplot(coverage, aes(chrom, mean_depth)) + geom_col(fill = "#4C78A8") + base_theme + labs(title = "Chromosome sequencing coverage", x = "Chromosome", y = "Mean sequencing depth"), "07_Chromosome_Sequencing_Coverage", 11, 6)

capture.output(sessionInfo(), file = file.path(out, "R_session_info.txt"))
writeLines(c("ONT core QC and methylation report", paste("Sample:", opt[["sample-id"]]), paste("Reference:", opt[["reference-name"]]), "Core sequencing-QC and coverage-weighted methylation figures were generated.", "Annotation-specific exploration was skipped because the complete GENCODE/CpG-island/cCRE/intergenic resource group was not supplied."), file.path(out, "methylation_exploration_report.txt"))
figures <- list.files(figs)
writeLines(paste0("<html><body><h1>ONT core QC and methylation</h1><p>Annotation-specific exploration was not configured.</p><ul>", paste0("<li><a href='figures/", figures, "'>", figures, "</a></li>", collapse = ""), "</ul></body></html>"), file.path(out, "ont_methylation_qc_report.html"))
