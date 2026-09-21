#!/usr/bin/env bash
# Stage 02: validate every chunk, then coordinate-sort once and index atomically.
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/lib/pipeline_common.sh"
CHECK_ONLY=0; [[ "${1:-}" == "--check-only" ]] && CHECK_ONLY=1
lock_stage 02_finalize_alignment; require_executable "$SAMTOOLS_BIN"
CHUNKS="${SAMPLE_OUTPUT}/01_alignment/aligned_unsorted_chunks"; OUT="${SAMPLE_OUTPUT}/02_alignment_qc"; mkdir -p "$OUT" "${SAMPLE_OUTPUT}/tmp" "${SAMPLE_OUTPUT}/00_manifests"
mapfile -t SOURCES < "$INPUT_BAM_LIST"; inputs=(); total=0
for source_bam in "${SOURCES[@]}"; do
  chunk="${CHUNKS}/$(basename -- "$source_bam" .bam).aligned.unsorted.bam"; [[ -s "$chunk" && -s "${chunk}.complete" ]] || { log "ERROR: missing complete Stage 01 chunk: $chunk"; exit 1; }
  "$SAMTOOLS_BIN" quickcheck -v "$chunk"; check_tags "$chunk"; count="$("$SAMTOOLS_BIN" view -@ "$VALIDATION_THREADS" -c "$chunk")"; [[ "$count" =~ ^[1-9][0-9]*$ ]] || exit 1
  total=$((total + count)); inputs+=("$chunk")
done
if (( CHECK_ONLY )); then log "CHECK-ONLY: ${#inputs[@]} Stage 01 chunks pass full validation"; exit 0; fi
final="${OUT}/${SAMPLE_ID}.aligned.sorted.bam"; bai="${final}.bai"; marker="${OUT}/.stage02.complete"
if [[ -s "$final" && -s "$bai" && -s "${OUT}/${SAMPLE_ID}.alignment_summary.txt" ]] && fresh_complete "$marker" "$final" "$bai" "${inputs[@]}" "$INPUT_BAM_LIST" "$PIPELINE_SETTINGS_FILE" && "$SAMTOOLS_BIN" quickcheck "$final" && "$SAMTOOLS_BIN" idxstats "$final" >/dev/null && check_tags "$final" && [[ "$("$SAMTOOLS_BIN" view -c "$final")" == "$total" ]]; then log 'SKIP: validated final BAM'; exit 0; fi
list="${SAMPLE_OUTPUT}/tmp/${SAMPLE_ID}.aligned_bams.list"; printf '%s\n' "${inputs[@]}" > "$list"; partial="${final}.partial.${BASHPID}"
"$SAMTOOLS_BIN" cat -b "$list" | "$SAMTOOLS_BIN" sort -@ "$SORT_THREADS" -m "$SORT_MEMORY_PER_THREAD" -o "$partial" -
"$SAMTOOLS_BIN" quickcheck -v "$partial"; [[ "$("$SAMTOOLS_BIN" view -@ "$VALIDATION_THREADS" -c "$partial")" == "$total" ]] || { log 'ERROR: sorted count differs from chunks'; exit 1; }
check_tags "$partial"
"$SAMTOOLS_BIN" index -@ "$SORT_THREADS" -o "${partial}.bai" "$partial"
"$SAMTOOLS_BIN" idxstats "$partial" >/dev/null
mv "$partial" "$final"; mv "${partial}.bai" "$bai"
"$SAMTOOLS_BIN" flagstat "$final" > "${OUT}/${SAMPLE_ID}.alignment_summary.txt.partial"; mv "${OUT}/${SAMPLE_ID}.alignment_summary.txt.partial" "${OUT}/${SAMPLE_ID}.alignment_summary.txt"
complete "$marker" "${SAMPLE_OUTPUT}/01_alignment/.stage01.complete" "$PIPELINE_SETTINGS_FILE"
