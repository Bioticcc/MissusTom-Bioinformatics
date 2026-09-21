#!/usr/bin/env bash
# Stage 01: align each supplied Dorado modBAM, retaining modified-base tags.
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/lib/pipeline_common.sh"
CHECK_ONLY=0; [[ "${1:-}" == "--check-only" ]] && CHECK_ONLY=1
[[ $# -eq 0 || "$1" == "--check-only" ]] || { echo "Usage: $0 [--check-only]" >&2; exit 2; }
lock_stage 01_align_modbam
require_executable "$DORADO_BIN"; require_executable "$SAMTOOLS_BIN"
ALIGN_DIR="${SAMPLE_OUTPUT}/01_alignment"; CHUNKS="${ALIGN_DIR}/aligned_unsorted_chunks"; mkdir -p "$CHUNKS" "${SAMPLE_OUTPUT}/00_manifests"
mapfile -t BAMS < "$INPUT_BAM_LIST"
[[ ${#BAMS[@]} -eq "$EXPECTED_PASS_BAM_COUNT" ]] || { log 'ERROR: generated input BAM list is inconsistent'; exit 1; }
for bam in "${BAMS[@]}"; do [[ -s "$bam" ]] || { log "ERROR: missing ONT BAM: $bam"; exit 1; }; done
if (( CHECK_ONLY )); then log "CHECK-ONLY: Stage 01 inputs and executables validate"; exit 0; fi
for source_bam in "${BAMS[@]}"; do
  name="$(basename -- "$source_bam" .bam)"; output="${CHUNKS}/${name}.aligned.unsorted.bam"; marker="${output}.complete"
  if [[ -s "$output" ]] && fresh_complete "$marker" "$output" "$source_bam" "$REFERENCE_MMI" "$PIPELINE_SETTINGS_FILE" && "$SAMTOOLS_BIN" quickcheck "$output" && check_tags "$output" && [[ "$("$SAMTOOLS_BIN" view -@ "$VALIDATION_THREADS" -c "$output")" == "$(awk -F '\t' '$1 == "record_count" {print $2}' "$marker")" ]]; then log "SKIP: validated $name"; continue; fi
  if [[ -e "$output" ]]; then mv "$output" "${SAMPLE_OUTPUT}/tmp/${name}.stale.${PIPELINE_RUN_STAMP}.bam"; fi
  if [[ -e "$marker" ]]; then mv "$marker" "${SAMPLE_OUTPUT}/tmp/${name}.stale.${PIPELINE_RUN_STAMP}.complete"; fi
  partial="${output}.partial.${BASHPID}"
  log "Aligning $source_bam with Dorado; MM/ML/MN tags must survive"
  "$DORADO_BIN" aligner --no-sort -t "$ALIGNMENT_THREADS" --mm2-opts '-x lr:hq -Y' "$REFERENCE_MMI" "$source_bam" > "$partial"
  "$SAMTOOLS_BIN" quickcheck -v "$partial"; records="$("$SAMTOOLS_BIN" view -@ "$VALIDATION_THREADS" -c "$partial")"
  [[ "$records" =~ ^[1-9][0-9]*$ ]] || { log "ERROR: empty aligned chunk: $source_bam"; exit 1; }
  check_tags "$partial"; mv "$partial" "$output"
  { printf 'status\tcomplete\nrecord_count\t%s\nsource_bam\t%s\n' "$records" "$source_bam"; } > "${marker}.partial"; mv "${marker}.partial" "$marker"
done
printf 'source_bam\n%s\n' "${BAMS[@]}" > "${SAMPLE_OUTPUT}/00_manifests/${SAMPLE_ID}.source_pass_bams.tsv"
complete "${ALIGN_DIR}/.stage01.complete" "$INPUT_BAM_LIST" "$REFERENCE_MMI" "$PIPELINE_SETTINGS_FILE"
