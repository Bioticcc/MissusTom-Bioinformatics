# Reference-complete ONT coverage

Implementation complete; full downloaded-data rerun [Awaiting manual testing].

The failed human run had 195 BAM/FAI contigs. Mosdepth omitted 11 wholly unaligned
contigs from its per-base output and summary, totaling 248,291 bases, while its
complete windows and thresholds recorded zero coverage. Its raw total length was
3,099,674,250 versus 3,099,922,541 FAI bases. A two-contig real Mosdepth example
reproduced the same validator failure. Existing run artifacts were read-only.

Stage 03 now passes its generated BAM idxstats to the summarizer. Whole-contig
omission is accepted only with matching BAM/FAI lengths, zero mapped reads and
complete zero-depth/threshold windows. Gaps and partial contigs are never filled.
Raw totals are validated against the contigs actually represented in the raw
summary; corrected means and breadth use every FAI base. Coverage tables record
the raw reference denominator and every added contig/base as audit metrics.

The helper streams a reference-complete BED into bgzip; Stage 03 publishes its
CSI index only after successful validation. Raw Mosdepth per-base output/index
and raw summaries/distributions remain available separately. A helper failure
leaves only temporary output and no completed-stage marker. Existing helper-based
freshness invalidates old coverage results; no project/schema migration is needed.

Validation: all 38 ONT workflow tests passed with the installed native tools and
R packages. New focused checks cover omission before/after observed contigs,
correct full-reference depth/breadth, indexed normalized tracks, raw provenance,
restart reuse, and rejection of missing corroboration, positive mapped counts,
nonzero window evidence, partial/gapped/reordered tracks, bad totals and length
mismatches. Python lint/format, shell syntax and scoped diff checks passed.

Operator: keep the existing project, select 5mC only, validate/save and rerun.
No full reference/BAM pipeline was launched as part of this implementation.
