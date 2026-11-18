#!/usr/bin/env Rscript
# Annotation-free descriptive report. Percentages retain the Stage 03/04 denominators.
suppressPackageStartupMessages({ library(data.table); library(ggplot2) })
args <- commandArgs(trailingOnly = TRUE)
if (length(args) %% 2L || any(!startsWith(args[seq(1L, length(args), 2L)], "--"))) stop("Options must be --key value pairs")
opt <- as.list(setNames(args[seq(2L, length(args), 2L)], sub("^--", "", args[seq(1L, length(args), 2L)])))
required <- c("sample-id", "organism", "reference-name", "main-chromosomes", "global-levels", "chromosome-methylation", "chromosome-coverage", "coverage-summary", "output-dir")
if (length(setdiff(required, names(opt)))) stop("Missing core report option")
mode <- opt[["modification-mode"]]; if (is.null(mode)) mode <- "5mc_5hmc"
if (!mode %in% c("5mc_only", "5mc_5hmc")) stop("Invalid modification mode")
joint <- mode == "5mc_5hmc"
measurement_note <- if (joint) "5mC and 5hmC measured separately" else "5mC only; 5hmC not measured. Total modified refers to measured 5mC only."
read_table <- function(key, optional = FALSE) {
  path <- opt[[key]]
  if (is.null(path) || !file.exists(path) || file.info(path)$size <= 0) {
    if (optional) return(data.table())
    stop("Missing report input: ", key)
  }
  fread(path, na.strings = c("NA", ""), integer64 = "double")
}
global <- read_table("global-levels"); chrom <- read_table("chromosome-methylation")
coverage <- read_table("chromosome-coverage"); coverage_summary <- read_table("coverage-summary")
if (!"percent_5mc" %in% names(chrom) && "pct_5mc_of_valid_calls" %in% names(chrom)) setnames(chrom, "pct_5mc_of_valid_calls", "percent_5mc")
if (!all(c("category", "percent_of_valid_calls", "call_count", "valid_call_denominator") %in% names(global))) stop("Invalid global summary columns")
if (!all(c("chrom", "percent_5mc") %in% names(chrom)) || !all(c("chrom", "mean_depth") %in% names(coverage))) stop("Invalid chromosome summary columns")
primary <- strsplit(opt[["main-chromosomes"]], ",", fixed = TRUE)[[1L]]
ordered <- function(x) {
  x <- copy(x)
  x[, chrom := factor(chrom, levels = rev(primary))]
  x
}
main_chrom <- ordered(chrom[chrom %in% primary]); main_coverage <- ordered(coverage[chrom %in% primary])
extras <- chrom[!chrom %in% primary]; extra_coverage <- coverage[!chrom %in% primary]
if (!nrow(main_chrom) || !nrow(main_coverage)) stop("No configured main chromosomes in report inputs")
call_coverage <- read_table("call-coverage", TRUE)
all_context <- read_table("modkit-summary", TRUE)
num <- function(x) suppressWarnings(as.numeric(x))
fmt <- function(x, digits = 0L) {
  value <- num(x)
  if (!length(value) || !is.finite(value[[1L]])) return("Not available")
  formatC(value[[1L]], format = "f", digits = digits, big.mark = ",")
}
pct <- function(x) if (identical(fmt(x, 2L), "Not available")) "Not available" else paste0(fmt(x, 2L), "%")
metric <- function(key) if (all(c("metric", "value") %in% names(coverage_summary))) coverage_summary[metric == key, value][1L] else NA_real_
gvalue <- function(category_name, column) global[category == category_name][[column]][1L]
field <- function(table, name) if (name %in% names(table)) table[[name]][1L] else NA_real_
genome <- if ("scope" %in% names(call_coverage)) call_coverage[scope == "genome"] else data.table()
valid <- num(gvalue("5mC", "valid_call_denominator"))
out <- opt[["output-dir"]]; figs <- file.path(out, "figures"); previews <- file.path(out, "previews"); tabs <- file.path(out, "tables")
for (directory in c(figs, previews, tabs)) dir.create(directory, recursive = TRUE, showWarnings = FALSE)
for (item in list(list(global, "global_methylation_plot_data"), list(chrom, "chromosome_methylation_plot_data"), list(coverage, "chromosome_coverage_plot_data"), list(coverage_summary, "coverage_summary_plot_data"), list(main_chrom, "primary_chromosome_methylation"), list(main_coverage, "primary_chromosome_coverage"), list(extras, "additional_contig_methylation"), list(extra_coverage, "additional_contig_coverage"))) fwrite(item[[1]], file.path(tabs, paste0(item[[2]], ".tsv")), sep = "\t", na = "NA")
identity <- paste(strwrap(paste(opt[["sample-id"]], "|", opt[["organism"]], "|", opt[["reference-name"]]), width = 95), collapse = "\n")
colors <- c("Unmodified C" = "#7B8794", "5mC" = "#147D92", "5hmC" = "#C17C16")
labels <- c("canonical_C" = "Unmodified C", "5mC" = "5mC", "5hmC" = "5hmC")
base_theme <- theme_minimal(base_size = 11) + theme(panel.grid.minor = element_blank(), panel.grid.major.y = element_blank(), plot.title = element_text(face = "bold"), plot.subtitle = element_text(size = 9, margin = margin(b = 10)), plot.caption = element_text(hjust = 0, size = 8), legend.title = element_blank(), legend.position = "bottom", plot.margin = margin(12, 20, 12, 12))
figure_names <- character(); figure_titles <- character()
save <- function(plot, name, title, height = 5.6) {
  plot <- plot + base_theme + labs(subtitle = identity)
  preview_plot <- unserialize(serialize(plot, NULL))
  ggsave(file.path(figs, paste0(name, ".pdf")), plot, width = 10, height = height, device = cairo_pdf, bg = "white")
  ggsave(file.path(previews, paste0(name, ".png")), preview_plot, width = 10, height = height, dpi = 120, type = "cairo", bg = "white")
  figure_names <<- c(figure_names, name); figure_titles <<- c(figure_titles, title)
}
composition <- global[category %in% c("canonical_C", "5mC", if (joint) "5hmC") & is.finite(percent_of_valid_calls)]
composition[, label := factor(labels[category], levels = names(colors))]
composition[, annotation := paste0(sprintf("%.2f%%", percent_of_valid_calls), "\nn = ", formatC(num(call_count), format = "f", digits = 0, big.mark = ","))]
save(ggplot(composition, aes(x = "CpG calls", y = percent_of_valid_calls, fill = label)) + geom_col(width = .5) + geom_text(aes(label = annotation), position = position_stack(vjust = .5), size = 3, color = "white", check_overlap = TRUE) + coord_flip() + scale_fill_manual(values = colors, breaks = if (joint) names(colors) else names(colors)[1:2], drop = TRUE) + scale_y_continuous(limits = c(0, 100)) + labs(title = "Composition of valid CpG calls", x = NULL, y = "Percent of valid CpG calls", caption = paste0("Denominator: ", fmt(valid), " valid calls at observed CpG sites.\n", measurement_note)), "01_Global_CpG_Modification_Composition", "CpG call composition", 3.8)
levels <- global[category %in% c("5mC", if (joint) "5hmC") & is.finite(percent_of_valid_calls)]
levels[, annotation := paste0(sprintf("%.2f%%", percent_of_valid_calls), "   n = ", formatC(num(call_count), format = "f", digits = 0, big.mark = ","))]
save(ggplot(levels, aes(x = category, y = percent_of_valid_calls, fill = category)) + geom_col(width = .5) + geom_text(aes(label = annotation), hjust = -.08, size = 3.5) + coord_flip(clip = "off") + scale_fill_manual(values = colors, guide = "none") + scale_y_continuous(limits = c(0, 100), breaks = seq(0, 100, 20), expand = expansion(mult = c(0, .12))) + labs(title = "Global CpG methylation", x = NULL, y = "Percent of valid CpG calls", caption = paste0("Weighted: modified calls / valid calls. Total modified = ", pct(gvalue("total_modified", "percent_of_valid_calls")), ".\n", measurement_note)), "02_Global_CpG_Methylation_Levels", "Global methylation", if (joint) 4.2 else 3.8)
main_chrom[, annotation := ifelse(is.finite(percent_5mc), paste0(sprintf("%.1f%%", percent_5mc), if ("valid_calls" %in% names(main_chrom)) paste0("  |  n=", formatC(num(main_chrom$valid_calls), format = "f", digits = 0, big.mark = ",")) else ""), "No valid calls")]
save(ggplot(main_chrom, aes(chrom, percent_5mc)) + geom_col(fill = colors[["5mC"]], width = .65, na.rm = TRUE) + geom_text(aes(y = 101, label = annotation), hjust = 0, size = 2.8) + coord_flip(clip = "off") + scale_y_continuous(limits = c(0, 100), breaks = seq(0, 100, 20), expand = expansion(mult = c(0, .35)), oob = scales::oob_keep) + labs(title = "5mC on main chromosomes", x = NULL, y = "Percent of valid CpG calls", caption = paste0("Each chromosome uses its own valid-call denominator (n). No calls means unavailable, not 0%.\n", nrow(extras), " additional contigs are retained in supporting tables; they are excluded from this panel.")), "06_Chromosome_CpG_Methylation_Levels", "Main-chromosome methylation", max(6, nrow(main_chrom) * .23 + 2.3))
main_coverage[, annotation := paste0(sprintf("%.3f", mean_depth), "x")]
save(ggplot(main_coverage, aes(chrom, mean_depth)) + scale_x_discrete(breaks = rev(primary), labels = rev(primary)) + geom_col(fill = "#486F9B", width = .65) + geom_text(aes(label = annotation), hjust = -.1, size = 3) + coord_flip(clip = "off") + scale_y_continuous(trans = "sqrt", breaks = pretty(sqrt(c(0, max(main_coverage$mean_depth, na.rm = TRUE) * 1.2)), n = 6)^2, expand = expansion(mult = c(0, .2))) + labs(title = "Sequencing depth on main chromosomes", x = NULL, y = "Mean sequencing depth (square-root axis)", caption = paste0("Labels show actual depth. A square-root axis preserves detail at low depth.\n", nrow(extra_coverage), " additional contigs are retained in supporting tables. Sequencing depth differs from valid-call depth.")), "07_Chromosome_Sequencing_Coverage", "Main-chromosome sequencing depth", max(6, nrow(main_coverage) * .23 + 2.3))
# Original flagstat counts distinguish primary reads from secondary/supplementary records.
flag_lines <- if (!is.null(opt[["alignment-flagstat"]]) && file.exists(opt[["alignment-flagstat"]])) readLines(opt[["alignment-flagstat"]], warn = FALSE) else character()
flag <- function(label) {
  line <- grep(paste0("^[0-9]+ \\+ [0-9]+ ", label, "(?: \\(|$)"), flag_lines, perl = TRUE, value = TRUE)
  if (length(line)) num(strsplit(line[[1]], " ")[[1]][1]) else NA_real_
}
primary_reads <- flag("primary"); primary_mapped <- flag("primary mapped")
stats_lines <- character()
if (!is.null(opt[["alignment-stats"]]) && file.exists(opt[["alignment-stats"]])) {
  connection <- file(opt[["alignment-stats"]], "rt")
  repeat {
    block <- readLines(connection, n = 10000L, warn = FALSE)
    if (!length(block)) break
    stats_lines <- c(stats_lines, grep("^SN\t", block, value = TRUE))
  }
  close(connection)
}
stats_value <- function(label) {
  for (line in stats_lines) {
    fields <- strsplit(line, "\t", fixed = TRUE)[[1L]]
    if (length(fields) >= 3 && fields[[2L]] == paste0(label, ":")) return(num(fields[[3L]]))
  }
  NA_real_
}
summary_value <- function(key) if (ncol(all_context) >= 2) all_context[all_context[[1]] == key][[2]][1L] else NA_real_
processing_events <- NA_real_
if (!is.null(opt[["workflow-log"]]) && file.exists(opt[["workflow-log"]])) {
  workflow_lines <- readLines(opt[["workflow-log"]], warn = FALSE)
  starts <- which(startsWith(workflow_lines, "RUN SAMPLE: "))
  current <- which(workflow_lines == paste("RUN SAMPLE:", opt[["sample-id"]]))
  if (length(current)) {
    first <- tail(current, 1L)
    next_sample <- starts[starts > first]
    last <- if (length(next_sample)) next_sample[[1L]] - 1L else length(workflow_lines)
    events <- grep("^> ~[0-9]+ failed processing", workflow_lines[first:last], value = TRUE)
    if (length(events)) processing_events <- sum(num(sub("^> ~([0-9]+).*", "\\1", events)))
  }
}
html_escape <- function(x) { x <- gsub("&", "&amp;", as.character(x), fixed = TRUE); x <- gsub("<", "&lt;", x, fixed = TRUE); gsub(">", "&gt;", x, fixed = TRUE) }
instrument_note <- "No original instrument report was supplied. Acquisition-wide yield and pass/fail QC are unavailable."
if (!is.null(opt[["instrument-report"]]) && nzchar(opt[["instrument-report"]]) && file.exists(opt[["instrument-report"]])) {
  uri <- paste0("file://", paste(vapply(strsplit(normalizePath(opt[["instrument-report"]]), "/", fixed = TRUE)[[1L]], utils::URLencode, character(1), reserved = TRUE), collapse = "/"))
  instrument_note <- paste0('Original acquisition QC is retained separately: <a href="', html_escape(uri), '">open the supplied instrument report</a>.')
}
row <- function(label, value) paste0("<tr><th>", html_escape(label), "</th><td>", html_escape(value), "</td></tr>")
card <- function(label, value) paste0('<div class="card"><span>', html_escape(label), '</span><strong>', html_escape(value), '</strong></div>')
cards <- paste(c(card("Primary mapped reads", fmt(primary_mapped)), card("Mean sequencing depth", paste0(fmt(metric("mean_depth"), 3), "x")), card("Reference covered at least once", pct(metric("pct_ge_1x"))), card("Global CpG 5mC", pct(gvalue("5mC", "percent_of_valid_calls"))), card("5hmC", if (joint) pct(gvalue("5hmC", "percent_of_valid_calls")) else "Not measured"), card("Valid CpG calls", fmt(valid))), collapse = "")
coverage_rows <- paste(vapply(c(1, 5, 10, 20), function(n) row(paste0("Reference bases at >=", n, "x"), paste0(fmt(metric(paste0("bases_ge_", n, "x"))), " (", pct(metric(paste0("pct_ge_", n, "x"))), ")")), character(1)), collapse = "")
call_labels <- c(reference_cpg_sites = "Reference CpG sites", cpg_sites_with_valid_calls = "CpG sites represented in pileup", pct_reference_cpg_sites_with_valid_calls = "Reference CpG sites represented (%)", valid_calls = "Valid CpG calls", failed_filtered_calls = "Failed or filtered CpG observations", no_call_calls = "No-call observations", deletion_calls = "Deletion observations", different_base_calls = "Different-base observations")
call_rows <- paste(vapply(c("reference_cpg_sites", "cpg_sites_with_valid_calls", "pct_reference_cpg_sites_with_valid_calls", "valid_calls", "failed_filtered_calls", "no_call_calls", "deletion_calls", "different_base_calls"), function(key) row(call_labels[[key]], if (startsWith(key, "pct_")) pct(field(genome, key)) else fmt(field(genome, key))), character(1)), collapse = "")
links <- paste0('<li><a href="tables/', list.files(tabs), '">', list.files(tabs), '</a></li>', collapse = "")
figure_panels <- paste(vapply(seq_along(figure_names), function(i) paste0('<article><h3>', figure_titles[[i]], '</h3><a href="figures/', figure_names[[i]], '.pdf"><img src="previews/', figure_names[[i]], '.png" alt="', html_escape(figure_titles[[i]]), '"></a><p><a href="figures/', figure_names[[i]], '.pdf">Download PDF</a></p></article>'), character(1)), collapse = "")
missing_rates <- sum(!is.finite(chrom$percent_5mc))
notice <- paste0("Percentages describe observed valid calls, not complete genome methylation. ", pct(metric("pct_zero_coverage")), " of reference bases have zero sequencing coverage. ", missing_rates, " contigs have no valid 5mC rate and remain unavailable rather than zero. A 100% value on a contig with very few calls is not strong evidence of uniform methylation.")
html <- paste0('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ONT QC: ', html_escape(opt[["sample-id"]]), '</title><style>body{font:16px system-ui,sans-serif;max-width:1120px;margin:32px auto;padding:0 20px;color:#243447;background:#f8fafc}h1,h2,h3{color:#173b50}header,section,article{background:white;padding:20px;margin:18px 0;border:1px solid #dbe4ea;border-radius:8px}header p{overflow-wrap:anywhere}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.card{padding:16px;background:#edf5f8}.card span,.card strong{display:block}.card strong{font-size:25px;margin-top:8px}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:9px;border-bottom:1px solid #dbe4ea}th{font-weight:500}img{width:100%;height:auto}.notice{padding:16px;background:#fff5dd;border-left:4px solid #bf8b21}a{color:#086c85}li{overflow-wrap:anywhere;margin:6px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}nav a{margin-right:16px}</style></head><body><header><h1>ONT sequencing and methylation QC</h1><p>', html_escape(identity), '</p><p>', html_escape(measurement_note), '</p><nav><a href="#summary">Summary</a><a href="#alignment">Alignment</a><a href="#coverage">Coverage</a><a href="#calls">Modification calls</a><a href="#figures">Figures</a><a href="#data">Data</a></nav></header><section id="summary"><h2>QC summary</h2><div class="metrics">', cards, '</div><p class="notice">', html_escape(notice), '</p></section><section id="alignment"><h2>Alignment and read accounting</h2><table>', row("Primary reads", fmt(primary_reads)), row("Primary mapped", fmt(primary_mapped)), row("Primary mapping percentage", pct(100 * primary_mapped / primary_reads)), row("Aligned-input bases (Samtools total length)", fmt(stats_value("total length"))), row("Mean input read length", paste0(fmt(stats_value("average length")), " bp")), row("Maximum input read length", paste0(fmt(stats_value("maximum length")), " bp")), row("Mapped reads with MAPQ 0", fmt(stats_value("reads MQ0"))), row("Secondary alignment records", fmt(flag("secondary"))), row("Supplementary alignment records", fmt(flag("supplementary"))), row("Reads used in all-context modification summary", fmt(summary_value("total_reads_used"))), row("Modkit failed-processing events (approximate, not unique reads)", fmt(processing_events)), '</table><p>These yield and length metrics describe the alignment input, not instrument-wide sequencing yield. Alignment records, modification-summary reads, and CpG calls are different scopes. Reads without usable modification tags may not contribute. The failed-processing count is transcribed from the sample block in the workflow log. It is approximate, may count a read more than once, and is distinct from failed/filtered CpG observations. Detailed rejection reasons were not recorded; they must not be inferred from this count.</p><details><summary>Original Samtools flagstat</summary><pre>', html_escape(paste(flag_lines, collapse = "\n")), '</pre></details></section><section id="coverage"><h2>Reference-wide sequencing coverage</h2><table>', coverage_rows, row("Zero-coverage reference bases", paste0(fmt(metric("zero_coverage_bases")), " (", pct(metric("pct_zero_coverage")), ")")), row("Excluded SAM flag mask", fmt(metric("mosdepth_exclude_flag_mask"))), row("Minimum mapping quality", fmt(metric("minimum_mapping_quality"))), '</table><p>These metrics include all reference contigs. The main-chromosome plots use only configured main chromosomes. Additional contigs remain in the downloadable tables.</p></section><section id="calls"><h2>CpG modification-call accounting</h2><table>', call_rows, '</table><p>Weighted 5mC = sum(5mC calls) / sum(valid CpG calls). Failed/filtered calls in this table are pileup observations, not counts of rejected reads. Empty denominators are unavailable. ', html_escape(measurement_note), '</p></section><section id="figures"><h2>Figures</h2>', figure_panels, '</section><section id="data"><h2>Data and provenance</h2><ul>', links, '<li><a href="methylation_exploration_report.txt">Text interpretation and scope</a></li><li><a href="R_session_info.txt">R session information</a></li><li><a href="report_input_checksums.tsv">Report input checksums</a></li></ul><p>', instrument_note, '</p><p>Annotation-specific exploration was not configured. Gene/region analyses require the complete annotation group. These are descriptive single-sample outputs; no differential methylation or biological significance is inferred.</p></section></body></html>')
writeLines(html, file.path(out, "ont_methylation_qc_report.html"), useBytes = TRUE)
writeLines(c("ONT core QC and methylation report", paste("Sample:", opt[["sample-id"]]), paste("Reference:", opt[["reference-name"]]), paste("Organism:", opt[["organism"]]), measurement_note, notice, "Main chromosomes are plotted separately; additional contigs remain in tables.", "Annotation-specific exploration was skipped because the complete GENCODE/CpG-island/cCRE/intergenic resource group was not supplied.", "Descriptive single-sample analysis; no statistical comparisons or significance are inferred."), file.path(out, "methylation_exploration_report.txt"))
input_keys <- c("global-levels", "chromosome-methylation", "chromosome-coverage", "coverage-summary", "call-coverage", "alignment-flagstat", "alignment-stats", "modkit-summary", "instrument-report")
input_paths <- unlist(opt[intersect(input_keys, names(opt))], use.names = TRUE)
source_arg <- grep("^--file=", commandArgs(), value = TRUE)
if (length(source_arg)) input_paths <- c(input_paths, "report-script" = sub("^--file=", "", source_arg[[1L]]))
input_paths <- input_paths[file.exists(input_paths)]
provenance <- data.table(input = names(input_paths), path = unname(input_paths), md5 = unname(tools::md5sum(input_paths)), generated_at_utc = format(Sys.time(), tz = "UTC", usetz = TRUE))
fwrite(provenance, file.path(out, "report_input_checksums.tsv"), sep = "\t")
capture.output(sessionInfo(), file = file.path(out, "R_session_info.txt"))
