#!/usr/bin/env bash
# Stage 04: high-depth-safe, strand-combined CpG pileup with separate 5mC/5hmC.
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/lib/pipeline_common.sh"
CHECK_ONLY=0; [[ "${1:-}" == "--check-only" ]] && CHECK_ONLY=1
lock_stage 04_methylation_analysis
for tool in "$SAMTOOLS_BIN" "$MODKIT_BIN" "$BGZIP_BIN" "$TABIX_BIN"; do require_executable "$tool"; done
ALIGN="${SAMPLE_OUTPUT}/02_alignment_qc/${SAMPLE_ID}.aligned.sorted.bam"; OUT="${SAMPLE_OUTPUT}/04_methylation"; WORK="${SAMPLE_OUTPUT}/tmp/stage04_work"; mkdir -p "$OUT" "$WORK"
[[ -s "$ALIGN" && -s "${ALIGN}.bai" && -s "$REFERENCE_FASTA" && -s "$REFERENCE_FAI" ]] || { log 'ERROR: Stage 02 BAM/index or reference missing'; exit 1; }
"$SAMTOOLS_BIN" quickcheck -v "$ALIGN"; check_tags "$ALIGN"
sample="$("$SAMTOOLS_BIN" view -F 4 "$ALIGN" 2>/dev/null | sed -n '1p')"; [[ "$sample" == *'C+m'* && "$sample" == *'C+h'* ]] || { log 'ERROR: modBAM lacks joint C+m/C+h calls'; exit 1; }
(( MODKIT_MAX_DEPTH <= 60000 )) || { log 'ERROR: MODKIT_MAX_DEPTH must not exceed 60000'; exit 1; }
if (( CHECK_ONLY )); then log 'CHECK-ONLY: MM/ML/MN and C+m/C+h Stage 04 prerequisites validate'; exit 0; fi
marker="${OUT}/.stage04.complete"
stage04_outputs_valid() {
  local file
  for file in modkit_tag_check.txt modkit_valid_mm_headers.tsv modkit_modified_bases.tsv modkit_all_context_summary.txt modkit_cpg_summary.txt cpg_5mc_5hmc.bed.gz cpg_5mc_5hmc.bed.gz.tbi global_methylation_levels.tsv chromosome_methylation_levels.tsv window_methylation_levels.tsv.gz window_methylation_levels.tsv.gz.tbi methylation_call_coverage.tsv methylation_analysis_report.txt; do [[ -s "${OUT}/${file}" ]] || return 1; done
  "$TABIX_BIN" -l "${OUT}/cpg_5mc_5hmc.bed.gz" >/dev/null 2>&1 || return 1
  "$TABIX_BIN" -l "${OUT}/window_methylation_levels.tsv.gz" >/dev/null 2>&1 || return 1
  awk -F '\t' 'NR > 1 && $2 == "5mC" {m=1} NR > 1 && $2 == "5hmC" {h=1} END {exit !(m && h)}' "${OUT}/global_methylation_levels.tsv"
}
stage04_outputs_valid && fresh_complete "$marker" "$ALIGN" "$REFERENCE_FASTA" "$REFERENCE_FAI" "$PIPELINE_SETTINGS_FILE" "$WORKFLOW_ROOT/lib/summarize_cpg_bedmethyl.py" && { log 'SKIP: current Stage 04 result'; exit 0; }
[[ ! -e "$marker" && -z "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]] || { mkdir -p "${SAMPLE_OUTPUT}/tmp/stale_stage04"; mv "$OUT" "${SAMPLE_OUTPUT}/tmp/stale_stage04/${PIPELINE_RUN_STAMP}"; mkdir -p "$OUT"; }
fingerprint="$( { stat -c '%n:%s:%Y' "$ALIGN" "$REFERENCE_FASTA" "$REFERENCE_FAI" "$PIPELINE_SETTINGS_FILE"; sha256sum "$0" "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/lib/summarize_cpg_bedmethyl.py"; } | sha256sum | awk '{print $1}' )"
RUN_WORK="${WORK}/${fingerprint}"; mkdir -p "$RUN_WORK"
"$MODKIT_BIN" modbam check-tags --threads "$MODKIT_THREADS" --num-reads "$MODKIT_TAG_CHECK_READS" --mapped-only --out-dir "${RUN_WORK}/tag_check.partial" --prefix tag_check "$ALIGN" > "${RUN_WORK}/modkit_tag_check.txt.partial" 2>&1
mv "${RUN_WORK}/modkit_tag_check.txt.partial" "${RUN_WORK}/modkit_tag_check.txt"; mv "${RUN_WORK}/tag_check.partial/tag_check_valid_mm_headers.tsv" "${RUN_WORK}/modkit_valid_mm_headers.tsv"; mv "${RUN_WORK}/tag_check.partial/tag_check_modified_bases.tsv" "${RUN_WORK}/modkit_modified_bases.tsv"
awk -F '\t' 'NR>1 && $2=="C" && $3=="m" {m=1} NR>1 && $2=="C" && $3=="h" {h=1} END {exit !(m&&h)}' "${RUN_WORK}/modkit_modified_bases.tsv" || { log 'ERROR: Modkit tag check did not confirm both C:m and C:h'; exit 1; }
"$MODKIT_BIN" summary --tsv --threads "$MODKIT_THREADS" --io-threads "$MODKIT_IO_THREADS" --reference "$REFERENCE_FASTA" --matched-only --filter-quantile "$MODKIT_FILTER_PERCENTILE" "$ALIGN" > "${RUN_WORK}/modkit_all_context_summary.txt"
awk -F '\t' 'BEGIN {OFS="\t"} {print $1,0,$2}' "$REFERENCE_FAI" > "${RUN_WORK}/reference_contigs.bed"
if [[ -s "${RUN_WORK}/cpg_5mc_5hmc.bed.gz" && -s "${RUN_WORK}/cpg_5mc_5hmc.bed.gz.tbi" ]] && "$TABIX_BIN" -l "${RUN_WORK}/cpg_5mc_5hmc.bed.gz" >/dev/null 2>&1; then
  log 'Reusing indexed CpG pileup from interrupted work'
else
partial="${RUN_WORK}/cpg_5mc_5hmc.partial.${BASHPID}.bed.gz"
"$MODKIT_BIN" pileup --threads "$MODKIT_THREADS" --io-threads "$MODKIT_IO_THREADS" --sampling-threads "$MODKIT_SAMPLING_THREADS" --bgzf-threads "$MODKIT_BGZF_THREADS" --reference "$REFERENCE_FASTA" --cpg --combine-strands --modified-bases 5mC 5hmC --filter-percentile "$MODKIT_FILTER_PERCENTILE" --num-reads "$MODKIT_SAMPLE_READS" --high-depth --max-depth "$MODKIT_MAX_DEPTH" --bgzf "$ALIGN" "$partial"
"$TABIX_BIN" -f -p bed "$partial"; mv "$partial" "${RUN_WORK}/cpg_5mc_5hmc.bed.gz"; mv "${partial}.tbi" "${RUN_WORK}/cpg_5mc_5hmc.bed.gz.tbi"
fi
"$MODKIT_BIN" stats --threads "$MODKIT_THREADS" --io-threads "$MODKIT_IO_THREADS" --regions "${RUN_WORK}/reference_contigs.bed" --out-table "${RUN_WORK}/modkit_cpg_summary.txt" "${RUN_WORK}/cpg_5mc_5hmc.bed.gz"
python3 "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/lib/summarize_cpg_bedmethyl.py" --fasta "$REFERENCE_FASTA" --fai "$REFERENCE_FAI" --bedmethyl "${RUN_WORK}/cpg_5mc_5hmc.bed.gz" --modkit-stats "${RUN_WORK}/modkit_cpg_summary.txt" --window-size "$METHYLATION_WINDOW_SIZE" --global-out "${RUN_WORK}/global_methylation_levels.tsv" --chromosome-out "${RUN_WORK}/chromosome_methylation_levels.tsv" --window-out "${RUN_WORK}/window_methylation_levels.tsv" --call-coverage-out "${RUN_WORK}/methylation_call_coverage.tsv"
"$BGZIP_BIN" -c "${RUN_WORK}/window_methylation_levels.tsv" > "${RUN_WORK}/window_methylation_levels.tsv.gz"; "$TABIX_BIN" -f -p bed "${RUN_WORK}/window_methylation_levels.tsv.gz"
printf 'ONT CpG methylation analysis\nSeparate 5mC and 5hmC records; values are coverage-weighted: sum(modified)/sum(valid).\nHigh-depth pileup cap: %s\n' "$MODKIT_MAX_DEPTH" > "${RUN_WORK}/methylation_analysis_report.txt"
for file in modkit_tag_check.txt modkit_valid_mm_headers.tsv modkit_modified_bases.tsv modkit_all_context_summary.txt modkit_cpg_summary.txt cpg_5mc_5hmc.bed.gz cpg_5mc_5hmc.bed.gz.tbi global_methylation_levels.tsv chromosome_methylation_levels.tsv window_methylation_levels.tsv.gz window_methylation_levels.tsv.gz.tbi methylation_call_coverage.tsv methylation_analysis_report.txt; do [[ -s "${RUN_WORK}/$file" ]] || { log "ERROR: missing Stage 04 result $file"; exit 1; }; done
for file in modkit_tag_check.txt modkit_valid_mm_headers.tsv modkit_modified_bases.tsv modkit_all_context_summary.txt modkit_cpg_summary.txt cpg_5mc_5hmc.bed.gz cpg_5mc_5hmc.bed.gz.tbi global_methylation_levels.tsv chromosome_methylation_levels.tsv window_methylation_levels.tsv.gz window_methylation_levels.tsv.gz.tbi methylation_call_coverage.tsv methylation_analysis_report.txt; do cp "${RUN_WORK}/$file" "${OUT}/${file}.partial"; mv "${OUT}/${file}.partial" "${OUT}/${file}"; done
awk -F '\t' 'NR>1 && $2=="5mC" {m=1} NR>1 && $2=="5hmC" {h=1} END {exit !(m&&h)}' "${OUT}/global_methylation_levels.tsv" || { log 'ERROR: summaries did not retain both modifications'; exit 1; }
stage04_outputs_valid || { log 'ERROR: Stage 04 output validation failed'; exit 1; }
complete "$marker" "$ALIGN" "$REFERENCE_FASTA" "$REFERENCE_FAI" "$PIPELINE_SETTINGS_FILE"
