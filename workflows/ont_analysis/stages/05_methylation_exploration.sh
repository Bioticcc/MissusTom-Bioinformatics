#!/usr/bin/env bash
# Stage 05 produces core QC/methylation plots; feature exploration needs all annotations.
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/lib/pipeline_common.sh"
CHECK_ONLY=0; [[ "${1:-}" == "--check-only" ]] && CHECK_ONLY=1
lock_stage 05_methylation_exploration; require_executable "$RSCRIPT_BIN"
S03="${SAMPLE_OUTPUT}/03_ont_qc_coverage"; S04="${SAMPLE_OUTPUT}/04_methylation"; OUT="${SAMPLE_OUTPUT}/05_methylation_exploration"; STAGE02_SUMMARY="${SAMPLE_OUTPUT}/02_alignment_qc/${SAMPLE_ID}.alignment_summary.txt"
for input in "${S03}/.stage03.complete" "${S04}/.stage04.complete" "${S04}/global_methylation_levels.tsv" "${S04}/chromosome_methylation_levels.tsv" "${S03}/chromosome_coverage.tsv" "${S03}/coverage_summary.tsv" "$STAGE02_SUMMARY"; do [[ -s "$input" ]] || { log "ERROR: Stage 05 input missing: $input"; exit 1; }; done
if (( CHECK_ONLY )); then "$RSCRIPT_BIN" --version >/dev/null; log 'CHECK-ONLY: Stage 05 core inputs validate'; exit 0; fi
ANNOTATIONS_ENABLED="${ANNOTATION_EXPLORATION_ENABLED:-0}"
if [[ "$ANNOTATIONS_ENABLED" == 1 ]]; then
  for input in "$METHYLATION_GENCODE_GFF3" "$METHYLATION_CPG_ISLANDS_JSON" "$METHYLATION_CCRE_TABLE" "$METHYLATION_INTERGENIC_BED"; do [[ -s "$input" ]] || { log "ERROR: Stage 05 annotation input missing: $input"; exit 1; }; done
  R_SCRIPT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/lib/methylation_exploration.R"
else R_SCRIPT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/lib/core_methylation_qc.R"; fi
marker="${OUT}/.stage05.complete"
outputs_valid() {
  [[ -s "$1/methylation_exploration_report.txt" && -s "$1/ont_methylation_qc_report.html" && -s "$1/R_session_info.txt" ]] || return 1
  if [[ "$ANNOTATIONS_ENABLED" == 1 ]]; then
    [[ -s "$1/tables/feature_methylation_summary.tsv" && -s "$1/tables/sixbase_figure_mapping.tsv" ]] || return 1
    [[ "$(find "$1/figures" -maxdepth 1 -type f -name '*.pdf' 2>/dev/null | wc -l)" -ge 23 ]] || return 1
    [[ "$(find "$1/tables" -maxdepth 1 -type f 2>/dev/null | wc -l)" -ge 19 ]]
  else
    [[ -s "$1/tables/global_methylation_plot_data.tsv" && -s "$1/tables/chromosome_methylation_plot_data.tsv" && -s "$1/tables/chromosome_coverage_plot_data.tsv" ]] || return 1
    [[ "$(find "$1/figures" -maxdepth 1 -type f -name '*.pdf' 2>/dev/null | wc -l)" -ge 4 ]]
  fi
}
freshness_inputs=("${S03}/.stage03.complete" "${S04}/.stage04.complete" "$STAGE02_SUMMARY" "$PIPELINE_SETTINGS_FILE" "$R_SCRIPT")
if [[ "$ANNOTATIONS_ENABLED" == 1 ]]; then
  freshness_inputs+=("$METHYLATION_GENCODE_GFF3" "$METHYLATION_CPG_ISLANDS_JSON" "$METHYLATION_CCRE_TABLE" "$METHYLATION_INTERGENIC_BED")
fi
[[ -z "$ONT_INSTRUMENT_REPORT" ]] || freshness_inputs+=("$ONT_INSTRUMENT_REPORT")
outputs_valid "$OUT" && fresh_complete "$marker" "${freshness_inputs[@]}" && { log 'SKIP: current Stage 05 result'; exit 0; }
[[ ! -e "$marker" && -z "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]] || { mkdir -p "${SAMPLE_OUTPUT}/tmp/stale_stage05"; mv "$OUT" "${SAMPLE_OUTPUT}/tmp/stale_stage05/${PIPELINE_RUN_STAMP}"; }
fingerprint="$( { stat -c '%n:%s:%Y' "${S03}/.stage03.complete" "${S04}/.stage04.complete" "$STAGE02_SUMMARY" "$PIPELINE_SETTINGS_FILE"; sha256sum "$R_SCRIPT"; } | sha256sum | awk '{print $1}' )"; WORK="${SAMPLE_OUTPUT}/tmp/stage05_work/${fingerprint}"; mkdir -p "$WORK"
if [[ "$ANNOTATIONS_ENABLED" == 1 ]]; then
  [[ -n "$ONT_INSTRUMENT_REPORT" && -s "$ONT_INSTRUMENT_REPORT" ]] || { printf 'No ONT instrument report was supplied.\n' > "$WORK/instrument_report_unavailable.txt"; ONT_INSTRUMENT_REPORT="$WORK/instrument_report_unavailable.txt"; }
  TMPDIR="$WORK" "$RSCRIPT_BIN" "$R_SCRIPT" --sample-id "$SAMPLE_ID" --reference-name "$REFERENCE_NAME" --fai "$REFERENCE_FAI" --global-levels "${S04}/global_methylation_levels.tsv" --chromosome-methylation "${S04}/chromosome_methylation_levels.tsv" --call-coverage "${S04}/methylation_call_coverage.tsv" --window-methylation "${S04}/window_methylation_levels.tsv.gz" --chromosome-coverage "${S03}/chromosome_coverage.tsv" --window-coverage "${S03}/window_coverage.tsv.gz" --alignment-stats "${S03}/alignment_stats.txt" --alignment-flagstat "${S03}/alignment_flagstat.txt" --coverage-summary "${S03}/coverage_summary.tsv" --stage02-summary "$STAGE02_SUMMARY" --instrument-report "$ONT_INSTRUMENT_REPORT" --bedmethyl "${S04}/cpg_5mc_5hmc.bed.gz" --gff3 "$METHYLATION_GENCODE_GFF3" --cpg-islands "$METHYLATION_CPG_ISLANDS_JSON" --ccre "$METHYLATION_CCRE_TABLE" --intergenic "$METHYLATION_INTERGENIC_BED" --output-dir "$WORK" --min-valid-coverage "$EXPLORATION_MIN_VALID_COVERAGE" --min-feature-cpgs "$EXPLORATION_MIN_FEATURE_CPGS" --top-window-count "$EXPLORATION_TOP_WINDOW_COUNT" --plot-dpi "$EXPLORATION_PLOT_DPI"
else TMPDIR="$WORK" "$RSCRIPT_BIN" "$R_SCRIPT" --sample-id "$SAMPLE_ID" --reference-name "$REFERENCE_NAME" --global-levels "${S04}/global_methylation_levels.tsv" --chromosome-methylation "${S04}/chromosome_methylation_levels.tsv" --chromosome-coverage "${S03}/chromosome_coverage.tsv" --coverage-summary "${S03}/coverage_summary.tsv" --output-dir "$WORK"; fi
outputs_valid "$WORK" || { log 'ERROR: missing Stage 05 core outputs'; exit 1; }
mkdir -p "$OUT"; mv "$WORK/figures" "$OUT/figures"; [[ ! -d "$WORK/tables" ]] || mv "$WORK/tables" "$OUT/tables"; for file in methylation_exploration_report.txt ont_methylation_qc_report.html R_session_info.txt; do mv "$WORK/$file" "$OUT/$file"; done
complete "$marker" "${freshness_inputs[@]}"
