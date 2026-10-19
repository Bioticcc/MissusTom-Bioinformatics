import type { CustomFigure, CustomFigureType } from "./types";

export const DEFAULT_FIGURES = [
  ["2D PCA", "Samples projected onto the first two expression components."],
  ["3D PCA projection", "A static PC1/PC2/PC3 projection, not an interactive 3D chart."],
  ["PCA scree plot", "Variance explained by each principal component."],
  ["Top DE genes heatmap", "Transformed expression for the leading qualifying genes."],
  ["Volcano plot", "Effect size and statistical evidence for each gene."],
  ["MA plot", "Expression level versus fold change for each gene."],
  ["P-value histogram", "Distribution of raw p-values."],
  ["Adjusted p-value histogram", "Distribution of multiple-testing adjusted p-values."],
  ["Fold-change density", "Distribution of shrunken log2 fold changes."],
  ["Sample-distance heatmap", "Similarity among transformed sample profiles."],
  ["DE count charts", "Up/down and total qualifying gene summaries."],
] as const;

export const FIGURE_TYPES: Record<CustomFigureType, { label: string; description: string }> = {
  gene_metric_scatter: { label: "Gene-metric scatter", description: "Compare two DESeq2 result measurements for genes." },
  sample_correlation_heatmap: { label: "Sample correlation heatmap", description: "Similarity of rlog expression profiles; not DE significance." },
  expression_distribution_boxplot: { label: "Expression distribution boxplot", description: "Descriptive rlog-normalized expression across samples or conditions." },
  top_de_genes_bar: { label: "Top differential genes bar chart", description: "Largest qualifying log2 fold changes for each comparison." },
  estimated_gene_count_bar: { label: "Estimated gene-count bar chart", description: "Per-sample estimated gene counts, not raw sequencing depth." },
};

export const GENE_METRICS = [
  ["base_mean", "Mean expression (baseMean)"], ["log2_fold_change", "Log2 fold change"],
  ["p_value", "P-value"], ["adjusted_p_value", "Adjusted p-value"],
  ["minus_log10_p_value", "−log10 p-value"], ["minus_log10_adjusted_p_value", "−log10 adjusted p-value"],
  ["stat", "Test statistic"], ["lfc_standard_error", "Log2 fold-change standard error"],
] as const;

export function newCustomFigure(type: CustomFigureType): CustomFigure {
  const base: CustomFigure = { figure_id: crypto.randomUUID(), figure_type: type, title: "", x_axis: { mode: "automatic" }, y_axis: { mode: "automatic" } };
  if (type === "gene_metric_scatter") return { ...base, x_variable: "base_mean", y_variable: "log2_fold_change" };
  if (type === "expression_distribution_boxplot") return { ...base, x_variable: "sample_id", y_variable: "rlog_expression" };
  if (type === "top_de_genes_bar") return { ...base, y_variable: "log2_fold_change", top_n: 20 };
  return base;
}
