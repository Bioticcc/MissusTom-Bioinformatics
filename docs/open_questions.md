# Open questions requiring confirmation

## Scientific design

1. Resolved for the current production contract: reads are paired-end and
   strandedness is an explicit project setting (`unstranded`, `forward`, or
   `reverse`). It is never inferred from filenames.
2. Should technical lanes be concatenated before trimming/quantification, passed
   together to kallisto, or quantified separately and combined later?
3. For human longitudinal samples, should DESeq2 use patient blocking or paired
   contrasts? The source reads `Patient` but currently fits `~group`.
4. Should human `Batch`, BMI, or other metadata enter the statistical design,
   visualization-only correction, or neither? Who approves covariates?
5. Resolved operationally for simple Bulk RNA-seq: two biological samples or
   replicate groups per comparison arm is the hard minimum, with a low-
   replication warning at exactly two. Whether a stricter laboratory policy
   should be configurable remains open.
6. Resolved for Bulk RNA-seq: every comparison is explicit numerator versus
   denominator, and positive log2 fold change means higher in the numerator.
7. Is `RHFD vs HFD` the intended mouse intervention comparison? Documentation
   also contains `HFDvsRHCD`, while no `RHCD` group is parsed in active code.
8. Are `HFD`, `ICD`, `RHFD`, and `RICD` the complete current mouse group set?
9. Should tissue be a first-class manifest field rather than a general
   covariate? The current application leaves it in optional covariates until the
   data model is confirmed.
10. Resolved for optional subset reporting: exact gene-biotype values
    `lncRNA`, `lincRNA`, `antisense`, `sense_intronic`, `sense_overlapping`,
    `bidirectional_promoter_lncrna`, `macro_lncrna`, and
    `3prime_overlapping_ncrna` count as lncRNA. All-gene analysis is always
    primary; unavailable classification is reported and skipped.

## References and methods

11. Resolved as a product contract rather than a pinned human bundle: users
    provide a transcriptome FASTA and matching GTF from the same release.
    Missus Tom validates transcript overlap and records reference checksums; it
    performs no live BioMart query.
12. Confirm the mouse GRCm39/vM38 resources; why is the annotation nested under a
    directory named `mouse_gencode_vM36`?
13. Resolved: Missus Tom builds with its managed Kallisto and reuses an atomic
    content-identified application cache. An explicit existing-index mode
    remains available with compatible annotation supplied by the user.
14. Confirm cutadapt adapter sequences, minimum length 20, quality threshold 20,
    and whether adapters vary by library kit.
15. Confirm whether `lfcThreshold=0.3` together with normal shrinkage matches the
    intended hypothesis/reporting semantics.
16. Is rlog required for every project despite cost, or may a validated VST path
    be used for larger cohorts?
17. Are enrichment outputs an intended future stage? No active enrichment stage
    was observed in the baseline source.

## Operations and acceptance

18. Which baseline outputs are contractual, and which legacy plots/tables may be
    retired?
19. What constitutes a complete/restartable sample and stage beyond file
    existence: tool exit, checksums, row counts, MultiQC inclusion, or all?
20. What synthetic or de-identified dataset and expected metrics may be used for
    equivalence testing?
21. Which container registry and version-review policy should be used for Docker
    and Apptainer images?
22. Where should shared references, indexes, application state, Nextflow work,
    and final projects live on laboratory workstations?

## ONT modified-base analysis

23. Should the initial 74-pass-BAM count remain a required project parameter,
    or should future ONT projects accept any explicitly confirmed chunk set?
24. Who approves upgrades to the managed dependency catalogs, and which complete
    platform-specific Samtools/R/Bioconductor package locks should eventually ship?
    The current installer pins ONT core tool targets but resolves other packages
    through conda-forge/Bioconda; offline bundles and full environment locks remain
    release-packaging work.
25. Can a future Stage 05 derive its run-summary panels without the MinKNOW HTML
    report? The faithful initial migration keeps it as a required provenance input.
26. Which versioned bundle owns GRCm38p6 FASTA/FAI/minimap2 index, GENCODE vM25, mm10 CpG
    islands, mouse cCREs, and intergenic intervals, and what checksums identify
    the reviewed bundle?
27. Must future ONT runs support multiple samples before differential methylation
    is added, or should multi-sample ingestion and DMR/DhMR inference arrive as
    one separately validated feature?
28. For future human ONT support, which chromosome naming/reference constraints
    and annotation-derived figures should replace the initial mouse-only rules?
29. What tiny public or synthetic modBAM fixture may be committed or generated
    for end-to-end regression testing of `MM`, `ML`, and `MN` preservation?
