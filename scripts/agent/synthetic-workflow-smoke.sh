#!/usr/bin/env bash
# Run a local, synthetic end-to-end smoke test without pulling Docker images or using user data.
# It creates synthetic data only under a UUID directory in .agent-work/synthetic-smoke.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
smoke_base="$repo_root/.agent-work/synthetic-smoke"
workflow="$repo_root/workflows/bulk_rnaseq/main.nf"

readonly FASTQC_IMAGE='quay.io/biocontainers/fastqc@sha256:e194048df39c3145d9b4e0a14f4da20b59d59250465b6f2a9cb698445fd45900'
readonly CUTADAPT_IMAGE='quay.io/biocontainers/cutadapt@sha256:c96a44c18f58660e853652c7efb303b3f426aa12f1ee7af007d03a54c39b87a5'
readonly KALLISTO_IMAGE='quay.io/biocontainers/kallisto@sha256:7615f563aa2948fd087f7e4a666e252f275c60b2070729bc9a3804c8873527e5'
readonly MULTIQC_IMAGE='quay.io/biocontainers/multiqc@sha256:dfd9fde2c48b896b884e79a71ddc16c72c97a0ee5c5c8e45aaba50f55d07d263'
readonly ANALYSIS_IMAGE='missus-tom/rnaseq-analysis:0.3.0'

usage() {
  cat <<'EOF'
Usage: ./scripts/agent/synthetic-workflow-smoke.sh

Creates a four-sample, 24-transcript artificial paired-read fixture and runs the
complete Docker Nextflow workflow. It uses only already-cached images, disables
container networking, and limits the local executor to 2 CPUs, 4 GiB, and one
task at a time. It never reads the restricted demo or external baseline.
EOF
}

if [[ ${1:-} == '--help' ]]; then
  usage
  exit 0
fi
if [[ $# -ne 0 ]]; then
  usage >&2
  exit 2
fi

command -v docker >/dev/null || { echo 'docker is required' >&2; exit 1; }
command -v nextflow >/dev/null || { echo 'nextflow is required' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'python3 is required' >&2; exit 1; }
[[ -f "$workflow" ]] || { echo "Workflow is missing: $workflow" >&2; exit 1; }

for image in "$FASTQC_IMAGE" "$CUTADAPT_IMAGE" "$KALLISTO_IMAGE" "$MULTIQC_IMAGE" "$ANALYSIS_IMAGE"; do
  docker image inspect "$image" >/dev/null 2>&1 || {
    echo "Required image is not cached locally (the script will not pull it): $image" >&2
    exit 1
  }
done

# Docker-created workflow files can be owned by root. Use a new UUID path for
# each run instead of attempting to remove those files; the Nextflow cache is
# safely shared under the ignored parent directory.
run_id=$(python3 -c 'import uuid; print(uuid.uuid4())')
smoke_root="$smoke_base/$run_id"
mkdir -p "$smoke_base/nxf"
mkdir -p "$smoke_root"/{input,references,results,work,logs,reports,tmp}

cleanup_owned_containers() {
  local exit_status=$? remaining
  local -a container_ids
  if (( exit_status == 0 )); then
    return
  fi
  if ! remaining=$(docker ps -aq --filter "label=missus_tom.run_id=$run_id"); then
    echo "Unable to inspect synthetic-run containers for $run_id" >&2
    return
  fi
  if [[ -n "$remaining" ]]; then
    echo "Removing failed synthetic-run containers for $run_id" >&2
    mapfile -t container_ids <<< "$remaining"
    docker rm -f "${container_ids[@]}" >&2 || echo "Unable to remove all synthetic-run containers for $run_id" >&2
  fi
}
trap cleanup_owned_containers EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

sequence_for() {
  local value=$1 output= position base
  for position in $(seq 1 220); do
    value=$(( (value * 1664525 + 1013904223) % 2147483647 ))
    case $((value % 4)) in
      0) base=A ;;
      1) base=C ;;
      2) base=G ;;
      *) base=T ;;
    esac
    output=$output$base
  done
  printf '%s' "$output"
}

reverse_complement() {
  printf '%s' "$1" | tr ACGT TGCA | rev
}

reference_dir="$smoke_root/references"
input_dir="$smoke_root/input"
: > "$reference_dir/transcripts.fa"
printf 'transcript_id\tgene_id\tgene_name\tgene_biotype\ttranscript_biotype\n' \
  > "$reference_dir/transcript_to_gene.tsv"
for index in $(seq 0 23); do
  sequence=$(sequence_for $((index + 17)))
  printf '%s' "$sequence" > "$reference_dir/sequence$index.txt"
  printf -v transcript 'TX%04d' $((index + 1))
  printf -v gene 'GENE%04d' $((index + 1))
  if (( index < 12 )); then
    gene_name=SMOKEPC$((index + 1))
    gene_type=protein_coding
  else
    gene_name=SMOKELNC$((index - 11))
    gene_type=lncRNA
  fi
  printf '>%s\n%s\n' "$transcript" "$sequence" >> "$reference_dir/transcripts.fa"
  printf '%s\t%s\t%s\t%s\t%s\n' \
    "$transcript" "$gene" "$gene_name" "$gene_type" "$gene_type" \
    >> "$reference_dir/transcript_to_gene.tsv"
done

for sample in H1 H2 OD1 OD2; do
  : > "$input_dir/${sample}_R1.fastq"
  : > "$input_dir/${sample}_R2.fastq"
  for index in $(seq 0 23); do
    low=$((35 + (index % 6) * 6))
    high=$((105 + (index % 5) * 13))
    if [[ "$sample" == H* ]]; then
      if (( index % 4 < 2 )); then count=$low; else count=$high; fi
    else
      if (( index % 4 < 2 )); then count=$high; else count=$low; fi
    fi
    case "$sample:$((index % 6))" in
      H1:0) offset=-8 ;; H1:1) offset=12 ;; H1:2) offset=-15 ;;
      H1:3) offset=20 ;; H1:4) offset=-5 ;; H1:5) offset=7 ;;
      H2:0) offset=13 ;; H2:1) offset=-17 ;; H2:2) offset=7 ;;
      H2:3) offset=-12 ;; H2:4) offset=18 ;; H2:5) offset=-6 ;;
      OD1:0) offset=-12 ;; OD1:1) offset=20 ;; OD1:2) offset=-5 ;;
      OD1:3) offset=8 ;; OD1:4) offset=-18 ;; OD1:5) offset=15 ;;
      OD2:0) offset=18 ;; OD2:1) offset=-8 ;; OD2:2) offset=12 ;;
      OD2:3) offset=-20 ;; OD2:4) offset=5 ;; OD2:5) offset=-14 ;;
    esac
    count=$((count + offset))
    sequence=$(< "$reference_dir/sequence$index.txt")
    read1=${sequence:0:50}
    read2=$(reverse_complement "${sequence: -50}")
    quality=$(printf 'I%.0s' $(seq 1 50))
    for pair in $(seq 1 "$count"); do
      printf '@%s_g%s_p%s/1\n%s\n+\n%s\n' "$sample" "$index" "$pair" "$read1" "$quality" >> "$input_dir/${sample}_R1.fastq"
      printf '@%s_g%s_p%s/2\n%s\n+\n%s\n' "$sample" "$index" "$pair" "$read2" "$quality" >> "$input_dir/${sample}_R2.fastq"
    done
  done
  gzip -c "$input_dir/${sample}_R1.fastq" > "$input_dir/${sample}_R1.fastq.gz"
  gzip -c "$input_dir/${sample}_R2.fastq" > "$input_dir/${sample}_R2.fastq.gz"
  rm "$input_dir/${sample}_R1.fastq" "$input_dir/${sample}_R2.fastq"
done
gzip -t "$input_dir"/*.fastq.gz

python3 - "$smoke_root/manifest.json" "$input_dir" "$reference_dir" <<'PY'
import json
import sys

manifest_path, input_dir, reference_dir = sys.argv[1:]
samples = []
for sample_id, condition in (("H1", "H"), ("H2", "H"), ("OD1", "OD1"), ("OD2", "OD1")):
    samples.append({
        "sample_id": sample_id,
        "included": True,
        "condition": condition,
        "r1_files": [f"{input_dir}/{sample_id}_R1.fastq.gz"],
        "r2_files": [f"{input_dir}/{sample_id}_R2.fastq.gz"],
    })
manifest = {
    "samples": samples,
    "comparisons": [{"comparison_id": "OD1_vs_H", "numerator": "OD1", "denominator": "H"}],
    "reference_resources": {
        "kallisto_index": f"{reference_dir}/kallisto.idx",
        "transcript_to_gene": f"{reference_dir}/transcript_to_gene.tsv",
    },
    "parameters": {"minimum_group_size": 2},
    "strandedness": "unstranded",
}
with open(manifest_path, "w", encoding="utf-8") as output:
    json.dump(manifest, output, indent=2)
    output.write("\n")
PY

docker run --rm --label "missus_tom.run_id=$run_id" --network none --cpus 2 --memory 1g --memory-swap 1g \
  -v "$smoke_root:/smoke:rw" "$KALLISTO_IMAGE" \
  kallisto index -i /smoke/references/kallisto.idx /smoke/references/transcripts.fa

TMPDIR="$smoke_root/tmp" NXF_TEMP="$smoke_root/tmp" NXF_HOME="$smoke_base/nxf" NXF_OPTS='-Xms256m -Xmx1g' \
  nextflow -log "$smoke_root/logs/nextflow-engine.log" run "$workflow" -profile docker \
    -work-dir "$smoke_root/work" \
    --manifest "$smoke_root/manifest.json" \
    --outdir "$smoke_root/results" \
    --max_cpus 2 --max_memory_gb 4 --max_parallel_tasks 1 --run_id "$run_id"

for output_directory in qc trimmed counts differential_expression figures tables; do
  output_path="$smoke_root/results/$output_directory"
  if [[ ! -d "$output_path" ]]; then
    echo "Synthetic run did not create $output_directory" >&2
    exit 1
  fi
  if ! output_file=$(find "$output_path" -type f -print -quit); then
    echo "Unable to inspect synthetic output directory: $output_directory" >&2
    exit 1
  fi
  if [[ -z "$output_file" ]]; then
    echo "Synthetic output directory is empty: $output_directory" >&2
    exit 1
  fi
done

trace_file="$smoke_root/logs/trace.tsv"
if [[ ! -f "$trace_file" ]]; then
  echo 'Synthetic run did not create a Nextflow trace' >&2
  exit 1
fi
if ! completed_or_cached=$(awk -F '\t' '
  NR == 1 {
    for (field = 1; field <= NF; field++) if ($field == "status") status_column = field
    next
  }
  $status_column == "COMPLETED" || $status_column == "CACHED" { count++ }
  END {
    if (!status_column) exit 2
    print count + 0
  }
' "$trace_file"); then
  echo 'Unable to parse completed tasks from the Nextflow trace' >&2
  exit 1
fi
if (( completed_or_cached != 19 )); then
  echo "Expected 19 completed or cached tasks in the Nextflow trace, got: $completed_or_cached" >&2
  exit 1
fi

if ! remaining=$(docker ps -aq --filter "label=missus_tom.run_id=$run_id"); then
  echo "Unable to inspect synthetic-run containers for $run_id" >&2
  exit 1
fi
if [[ -n "$remaining" ]]; then
  echo "Synthetic run left owned containers for $run_id: $remaining" >&2
  exit 1
fi
trap - EXIT
printf 'Synthetic smoke completed: %s\n' "$smoke_root"
