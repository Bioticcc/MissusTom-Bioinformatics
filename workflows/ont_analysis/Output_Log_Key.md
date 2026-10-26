# ONT Analysis output log key

This is a read-only reference for the live ONT run log shown in Missus Tom.
It explains log families and prefixes; it does not change the workflow or the
scientific interpretation of outputs.

## Missus Tom and runner records

| Header or pattern | Meaning | Information used |
| --- | --- | --- |
| `[Missus Tom lifecycle]` | Application-owned queue, validation, heartbeat, cleanup, cancellation, and final-status record. | Run state and UTC time. This is protected application output. |
| `Heartbeat at ... workflow is still running` | The backend remains responsible for the run and has not observed a terminal process state. It is not a stage completion estimate. | Elapsed run time. |
| `RUN: bash .../stages/01_align_modbam.sh` | The ONT Python runner is launching a fixed stage script. The stage filename is used by the app to show current runner state. | Fixed stage path. This prefix is protected. |
| `ERROR: ...` | The Python runner caught a manifest, filesystem, or stage-command failure. The following detail identifies the immediate cause. | Runner validation or subprocess error text. |
| `CHECK-ONLY:` | A validation-only invocation completed without running scientific processing. | Manifest, paths, tools, and generated configuration. |

## ONT stage records

| Header or pattern | Meaning | Information used |
| --- | --- | --- |
| `[YYYY-MM-DDTHH:MM:SS±ZZZZ] ...` | Timestamped message emitted by a Bash ONT stage. The timestamp is local-offset ISO-8601 format. | Stage status text and current time. |
| `Aligning ... with Dorado; MM/ML/MN tags must survive` | Stage 01 is aligning an input modBAM while preserving modified-base tags. | Source BAM, reference minimap2 index, and Dorado. |
| `SKIP: validated ...` | A restartable stage found current outputs and its completion/freshness checks passed, so it is reusing them. | Marker files, input timestamps, and validation commands. |
| `ERROR: missing ...`, `ERROR: ... validation failed` | A stage prerequisite or output contract failed. | Named input, output, tag, or validation condition. |
| `Reusing indexed CpG pileup from interrupted work` | Stage 04 found a reusable validated intermediate from an interrupted run. | Prior pileup intermediate and freshness checks. |

## External-tool records

| Header or pattern | Meaning | Information used |
| --- | --- | --- |
| `dorado` | Dorado alignment output or error. | Input BAM, reference index, and alignment settings. |
| `samtools` | BAM validation, sorting, indexing, read-count, flagstat, or idxstats output. | Aligned BAM and its index. |
| `mosdepth` | Coverage calculation output. | Final aligned BAM, index, and coverage parameters. |
| `modkit` | Modified-base pileup/filtering output. | modBAM MM/ML/MN tags, reference, and depth/filter settings. |
| `R` messages such as `Stage 05 R analysis`, `Saved figure`, or `CpG sites loaded` | Stage 05 exploration progress. | Validated CpG tables, coverage summaries, optional annotations, and plotting settings. |
| `Traceback`, `Exception`, or `CalledProcessError` | Python/R/tool failure context. The earliest error in the sequence is normally the useful one. | The failing program and its arguments/files. |

## Important boundaries

- Tool output can use stdout or stderr. A stderr line is not automatically a
  failure; look for an explicit error, non-zero exit status, or terminal run
  status.
- Logs can contain path names and command details. They are diagnostic
  records, not a substitute for the output manifests and scientific QC files.
