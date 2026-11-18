#!/usr/bin/env bash
# Stage 04: high-depth-safe, strand-combined CpG pileup with separate 5mC/5hmC.
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/lib/pipeline_common.sh"
MODE="${MODIFICATION_MODE:-5mc_5hmc}"
if [[ "$MODE" == 5mc_only ]]; then CPG_STEM=cpg_5mc; MODIFICATIONS=(5mC)
elif [[ "$MODE" == 5mc_5hmc ]]; then CPG_STEM=cpg_5mc_5hmc; MODIFICATIONS=(5mC 5hmC)
else log 'ERROR: invalid modification mode'; exit 1; fi
summary_modifications_valid() {
  awk -F '\t' -v mode="$MODE" 'NR>1 && $2=="5mC" && $4!="NA" {m=1} NR>1 && $2=="5hmC" && ((mode=="5mc_only" && $4=="NA" && $10=="not_measured") || (mode=="5mc_5hmc" && $4!="NA")) {h=1} END {exit !(m&&h)}' "$1"
}
CHECK_ONLY=0; [[ "${1:-}" == "--check-only" ]] && CHECK_ONLY=1
lock_stage 04_methylation_analysis
for tool in "$SAMTOOLS_BIN" "$MODKIT_BIN" "$BGZIP_BIN" "$TABIX_BIN"; do require_executable "$tool"; done
ALIGN="${SAMPLE_OUTPUT}/02_alignment_qc/${SAMPLE_ID}.aligned.sorted.bam"; OUT="${SAMPLE_OUTPUT}/04_methylation"; WORK="${SAMPLE_OUTPUT}/tmp/stage04_work"; mkdir -p "$OUT" "$WORK"
[[ -s "$ALIGN" && -s "${ALIGN}.bai" && -s "$REFERENCE_FASTA" && -s "$REFERENCE_FAI" ]] || { log 'ERROR: Stage 02 BAM/index or reference missing'; exit 1; }
"$SAMTOOLS_BIN" quickcheck -v "$ALIGN"; check_tags "$ALIGN"
# Modkit's sampled tag check below confirms the selected modification codes. MM permits
# combined C+mh encoding and individual mapped reads may have no modified sites.
(( MODKIT_MAX_DEPTH <= 60000 )) || { log 'ERROR: MODKIT_MAX_DEPTH must not exceed 60000'; exit 1; }
if (( CHECK_ONLY )); then log 'CHECK-ONLY: Modification tags validate; Modkit confirms the selected measurement mode during execution'; exit 0; fi
marker="${OUT}/.stage04.complete"
stage04_outputs_valid() {
  local file
  for file in modkit_tag_check.txt modkit_valid_mm_headers.tsv modkit_modified_bases.tsv modkit_all_context_summary.txt modkit_cpg_summary.txt ${CPG_STEM}.bed.gz ${CPG_STEM}.bed.gz.tbi global_methylation_levels.tsv chromosome_methylation_levels.tsv window_methylation_levels.tsv.gz window_methylation_levels.tsv.gz.tbi methylation_call_coverage.tsv methylation_analysis_report.txt; do [[ -s "${OUT}/${file}" ]] || return 1; done
  "$TABIX_BIN" -l "${OUT}/${CPG_STEM}.bed.gz" >/dev/null 2>&1 || return 1
  "$TABIX_BIN" -l "${OUT}/window_methylation_levels.tsv.gz" >/dev/null 2>&1 || return 1
  summary_modifications_valid "${OUT}/global_methylation_levels.tsv"
}
stage04_outputs_valid && fresh_complete "$marker" "$ALIGN" "$REFERENCE_FASTA" "$REFERENCE_FAI" "$PIPELINE_SETTINGS_FILE" "$MODKIT_BIN" "$WORKFLOW_ROOT/lib/summarize_cpg_bedmethyl.py" && { log 'SKIP: current Stage 04 result'; exit 0; }
[[ ! -e "$marker" && -z "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]] || { mkdir -p "${SAMPLE_OUTPUT}/tmp/stale_stage04"; mv "$OUT" "${SAMPLE_OUTPUT}/tmp/stale_stage04/${PIPELINE_RUN_STAMP}"; mkdir -p "$OUT"; }
fingerprint="$( { stat -c '%n:%s:%Y' "$ALIGN" "$REFERENCE_FASTA" "$REFERENCE_FAI" "$PIPELINE_SETTINGS_FILE"; sha256sum "$MODKIT_BIN" "$0" "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/lib/summarize_cpg_bedmethyl.py"; } | sha256sum | awk '{print $1}' )"
RUN_WORK="${WORK}/${fingerprint}"; mkdir -p "$RUN_WORK"
"$MODKIT_BIN" modbam check-tags --force --threads "$MODKIT_THREADS" --num-reads "$MODKIT_TAG_CHECK_READS" --mapped-only --out-dir "${RUN_WORK}/tag_check.partial" --prefix tag_check "$ALIGN" > "${RUN_WORK}/modkit_tag_check.txt.partial" 2>&1
mv "${RUN_WORK}/modkit_tag_check.txt.partial" "${RUN_WORK}/modkit_tag_check.txt"; mv "${RUN_WORK}/tag_check.partial/tag_check_valid_mm_headers.tsv" "${RUN_WORK}/modkit_valid_mm_headers.tsv"; mv "${RUN_WORK}/tag_check.partial/tag_check_modified_bases.tsv" "${RUN_WORK}/modkit_modified_bases.tsv"
awk -F '\t' -v mode="$MODE" 'NR>1 && $2=="C" && $3=="m" {m=1} NR>1 && $2=="C" && $3=="h" {h=1} END {exit !(m && ((mode=="5mc_only" && !h) || (mode=="5mc_5hmc" && h)))}' "${RUN_WORK}/modkit_modified_bases.tsv" || { log 'ERROR: Modkit tag check does not match the selected modification mode; select 5mC-only for m calls or joint mode for m+h calls'; exit 1; }
"$MODKIT_BIN" summary --tsv --threads "$MODKIT_THREADS" --io-threads "$MODKIT_IO_THREADS" --reference "$REFERENCE_FASTA" --matched-only --filter-quantile "$MODKIT_FILTER_PERCENTILE" "$ALIGN" > "${RUN_WORK}/modkit_all_context_summary.txt"
awk -F '\t' 'BEGIN {OFS="\t"} {print $1,0,$2}' "$REFERENCE_FAI" > "${RUN_WORK}/reference_contigs.bed"
if [[ -s "${RUN_WORK}/${CPG_STEM}.bed.gz" && -s "${RUN_WORK}/${CPG_STEM}.bed.gz.tbi" ]] && "$TABIX_BIN" -l "${RUN_WORK}/${CPG_STEM}.bed.gz" >/dev/null 2>&1; then
  log 'Reusing indexed CpG pileup from interrupted work'
else
partial="${RUN_WORK}/${CPG_STEM}.partial.${BASHPID}.bed.gz"
"$MODKIT_BIN" pileup --threads "$MODKIT_THREADS" --io-threads "$MODKIT_IO_THREADS" --sampling-threads "$MODKIT_SAMPLING_THREADS" --bgzf-threads "$MODKIT_BGZF_THREADS" --reference "$REFERENCE_FASTA" --cpg --combine-strands --modified-bases "${MODIFICATIONS[@]}" --filter-percentile "$MODKIT_FILTER_PERCENTILE" --num-reads "$MODKIT_SAMPLE_READS" --high-depth --max-depth "$MODKIT_MAX_DEPTH" --bgzf "$ALIGN" "$partial"
"$TABIX_BIN" -f -p bed "$partial"; mv "$partial" "${RUN_WORK}/${CPG_STEM}.bed.gz"; mv "${partial}.tbi" "${RUN_WORK}/${CPG_STEM}.bed.gz.tbi"
fi
"$MODKIT_BIN" stats --threads "$MODKIT_THREADS" --io-threads "$MODKIT_IO_THREADS" --regions "${RUN_WORK}/reference_contigs.bed" --out-table "${RUN_WORK}/modkit_cpg_summary.txt" "${RUN_WORK}/${CPG_STEM}.bed.gz"
python3 "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/lib/summarize_cpg_bedmethyl.py" --modification-mode "$MODE" --fasta "$REFERENCE_FASTA" --fai "$REFERENCE_FAI" --bedmethyl "${RUN_WORK}/${CPG_STEM}.bed.gz" --modkit-stats "${RUN_WORK}/modkit_cpg_summary.txt" --window-size "$METHYLATION_WINDOW_SIZE" --global-out "${RUN_WORK}/global_methylation_levels.tsv" --chromosome-out "${RUN_WORK}/chromosome_methylation_levels.tsv" --window-out "${RUN_WORK}/window_methylation_levels.tsv" --call-coverage-out "${RUN_WORK}/methylation_call_coverage.tsv"
"$BGZIP_BIN" -c "${RUN_WORK}/window_methylation_levels.tsv" > "${RUN_WORK}/window_methylation_levels.tsv.gz"; "$TABIX_BIN" -f -p bed "${RUN_WORK}/window_methylation_levels.tsv.gz"
printf 'ONT CpG methylation analysis\nMeasurement mode: %s. Values are coverage-weighted: sum(modified)/sum(valid).\nHigh-depth pileup cap: %s\n' "$MODE" "$MODKIT_MAX_DEPTH" > "${RUN_WORK}/methylation_analysis_report.txt"
[[ "$MODE" != 5mc_only ]] || printf '5hmC: not measured. Total modified counts include measured 5mC only.\n' >> "${RUN_WORK}/methylation_analysis_report.txt"
for file in modkit_tag_check.txt modkit_valid_mm_headers.tsv modkit_modified_bases.tsv modkit_all_context_summary.txt modkit_cpg_summary.txt ${CPG_STEM}.bed.gz ${CPG_STEM}.bed.gz.tbi global_methylation_levels.tsv chromosome_methylation_levels.tsv window_methylation_levels.tsv.gz window_methylation_levels.tsv.gz.tbi methylation_call_coverage.tsv methylation_analysis_report.txt; do [[ -s "${RUN_WORK}/$file" ]] || { log "ERROR: missing Stage 04 result $file"; exit 1; }; done
for file in modkit_tag_check.txt modkit_valid_mm_headers.tsv modkit_modified_bases.tsv modkit_all_context_summary.txt modkit_cpg_summary.txt ${CPG_STEM}.bed.gz ${CPG_STEM}.bed.gz.tbi global_methylation_levels.tsv chromosome_methylation_levels.tsv window_methylation_levels.tsv.gz window_methylation_levels.tsv.gz.tbi methylation_call_coverage.tsv methylation_analysis_report.txt; do cp "${RUN_WORK}/$file" "${OUT}/${file}.partial"; mv "${OUT}/${file}.partial" "${OUT}/${file}"; done
summary_modifications_valid "${OUT}/global_methylation_levels.tsv" || { log 'ERROR: summary measurement availability does not match selected mode'; exit 1; }
stage04_outputs_valid || { log 'ERROR: Stage 04 output validation failed'; exit 1; }
complete "$marker" "$ALIGN" "$REFERENCE_FASTA" "$REFERENCE_FAI" "$PIPELINE_SETTINGS_FILE"
