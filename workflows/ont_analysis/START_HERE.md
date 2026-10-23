# Start here: ONT Analysis

This pipeline processes mouse Oxford Nanopore modBAM files in five ordered
stages. It checks alignment, measures quality and coverage, and summarizes DNA
methylation.

## How the files connect

1. `run_pipeline.py` is the main runner. It reads the project settings and runs
   each stage in order.
2. `stages/01_align_modbam.sh` prepares the aligned modified-base BAM data.
3. `stages/02_finalize_alignment.sh` checks and publishes the alignment files.
4. `stages/03_ont_qc_and_coverage.sh` creates quality and coverage summaries.
5. `stages/04_methylation_analysis.sh` creates methylation calls and core
   methylation summaries.
6. `stages/05_methylation_exploration.sh` creates the final exploration tables,
   figures, and reports.
7. Files under `lib/` are helpers used by those stages. Python helpers summarize
   tables, R helpers create scientific summaries and figures, and
   `pipeline_common.sh` provides shared shell functions.

The runner, stages, and helpers must come from the same saved pipeline revision.

## Before changing a file

- Start with one small change and keep notes about why you made it.
- Keep the stage order and the expected output file names unless you also
  understand every place that uses them.
- Preserve modified-base information. Do not remove the MM, ML, or MN BAM tags.
- 5mC and 5hmC are different measurements and should not be combined silently.
- CPU and memory limits do not stop custom code from accessing files available
  to your user account.
- A script can run without errors and still produce scientifically incorrect
  results. Review custom results carefully.

Missus Tom keeps the official pipeline unchanged. You can restore it from this
page if a custom version does not work.
