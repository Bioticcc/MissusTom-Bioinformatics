#!/usr/bin/env bash
# Stage 03: normal shebang (the external baseline's `cd #!` typo is fixed here).
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/lib/pipeline_common.sh"
CHECK_ONLY=0; [[ "${1:-}" == "--check-only" ]] && CHECK_ONLY=1
lock_stage 03_ont_qc_and_coverage
for tool in "$SAMTOOLS_BIN" "$MOSDEPTH_BIN" "$BGZIP_BIN" "$TABIX_BIN"; do require_executable "$tool"; done
ALIGN="${SAMPLE_OUTPUT}/02_alignment_qc/${SAMPLE_ID}.aligned.sorted.bam"; OUT="${SAMPLE_OUTPUT}/03_ont_qc_coverage"; TMP="${SAMPLE_OUTPUT}/tmp/stage03.${PIPELINE_RUN_STAMP}"; mkdir -p "$OUT" "$TMP"
[[ -s "$ALIGN" && -s "${ALIGN}.bai" && -s "$REFERENCE_FAI" ]] || { log 'ERROR: Stage 02 BAM/index or reference FAI missing'; exit 1; }
"$SAMTOOLS_BIN" quickcheck -v "$ALIGN"; check_tags "$ALIGN"
if (( CHECK_ONLY )); then log 'CHECK-ONLY: Stage 03 prerequisites validate'; exit 0; fi
marker="${OUT}/.stage03.complete"
stage03_outputs_valid() {
  local file
  for file in alignment_flagstat.txt alignment_stats.txt alignment_idxstats.tsv coverage_summary.tsv chromosome_coverage.tsv window_coverage.tsv.gz window_coverage.tsv.gz.tbi per_base_coverage.bed.gz per_base_coverage.bed.gz.csi zero_low_coverage_intervals.bed.gz zero_low_coverage_intervals.bed.gz.tbi mosdepth.global.dist.txt mosdepth.region.dist.txt mosdepth.summary.txt ont_qc_coverage_report.txt; do [[ -s "${OUT}/${file}" ]] || return 1; done
  "$TABIX_BIN" -l "${OUT}/window_coverage.tsv.gz" >/dev/null 2>&1 && "$TABIX_BIN" -l "${OUT}/per_base_coverage.bed.gz" >/dev/null 2>&1 && "$TABIX_BIN" -l "${OUT}/zero_low_coverage_intervals.bed.gz" >/dev/null 2>&1
}
stage03_outputs_valid && fresh_complete "$marker" "$ALIGN" "$REFERENCE_FAI" "$PIPELINE_SETTINGS_FILE" "$WORKFLOW_ROOT/lib/summarize_mosdepth.py" && { log 'SKIP: current Stage 03 result'; exit 0; }
[[ ! -e "$marker" && -z "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]] || { mkdir -p "${SAMPLE_OUTPUT}/tmp/stale_stage03"; mv "$OUT" "${SAMPLE_OUTPUT}/tmp/stale_stage03/${PIPELINE_RUN_STAMP}"; mkdir -p "$OUT"; }
prefix="${TMP}/${SAMPLE_ID}"
"$SAMTOOLS_BIN" flagstat -@ "$QC_THREADS" "$ALIGN" > "${TMP}/alignment_flagstat.txt"; "$SAMTOOLS_BIN" stats -@ "$QC_THREADS" "$ALIGN" > "${TMP}/alignment_stats.txt"; "$SAMTOOLS_BIN" idxstats -@ "$QC_THREADS" "$ALIGN" > "${TMP}/alignment_idxstats.tsv"
MOSDEPTH_PRECISION=6 "$MOSDEPTH_BIN" --threads "$QC_THREADS" --by "$COVERAGE_WINDOW_SIZE" --thresholds "$COVERAGE_THRESHOLDS" --flag "$COVERAGE_EXCLUDE_FLAGS" --mapq "$COVERAGE_MIN_MAPQ" "$prefix" "$ALIGN"
python3 "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/lib/summarize_mosdepth.py" --fai "$REFERENCE_FAI" --regions "${prefix}.regions.bed.gz" --thresholds-bed "${prefix}.thresholds.bed.gz" --per-base "${prefix}.per-base.bed.gz" --mosdepth-summary "${prefix}.mosdepth.summary.txt" --coverage-summary-out "${TMP}/coverage_summary.tsv" --chromosome-out "${TMP}/chromosome_coverage.tsv" --window-out "${TMP}/window_coverage.tsv" --low-interval-out "${TMP}/zero_low_coverage_intervals.bed" --thresholds "$COVERAGE_THRESHOLDS" --window-size "$COVERAGE_WINDOW_SIZE" --low-depth-threshold "$LOW_COVERAGE_DEPTH_THRESHOLD" --low-window-min-1x-breadth "$LOW_COVERAGE_MIN_1X_BREADTH_PERCENT" --exclude-flags "$COVERAGE_EXCLUDE_FLAGS" --min-mapq "$COVERAGE_MIN_MAPQ"
"$BGZIP_BIN" -c "${TMP}/window_coverage.tsv" > "${TMP}/window_coverage.tsv.gz"; "$TABIX_BIN" -f -p bed "${TMP}/window_coverage.tsv.gz"; "$BGZIP_BIN" -c "${TMP}/zero_low_coverage_intervals.bed" > "${TMP}/zero_low_coverage_intervals.bed.gz"; "$TABIX_BIN" -f -p bed "${TMP}/zero_low_coverage_intervals.bed.gz"
mv "${prefix}.per-base.bed.gz" "${TMP}/per_base_coverage.bed.gz"; mv "${prefix}.per-base.bed.gz.csi" "${TMP}/per_base_coverage.bed.gz.csi"; mv "${prefix}.mosdepth.global.dist.txt" "${TMP}/mosdepth.global.dist.txt"; mv "${prefix}.mosdepth.region.dist.txt" "${TMP}/mosdepth.region.dist.txt"; cp "${prefix}.mosdepth.summary.txt" "${TMP}/mosdepth.summary.txt"
printf 'ONT alignment QC and coverage; exact run-length depth retained.\n' > "${TMP}/ont_qc_coverage_report.txt"
for file in "$TMP"/*; do mv "$file" "$OUT/"; done
stage03_outputs_valid || { log 'ERROR: Stage 03 output validation failed'; exit 1; }
complete "$marker" "$ALIGN" "$REFERENCE_FAI" "$PIPELINE_SETTINGS_FILE"
