# Open questions requiring confirmation

## Scientific design

1. Is the current library chemistry always paired-end and reverse/RF stranded,
   or must this vary per project or sample?
2. Should technical lanes be concatenated before trimming/quantification, passed
   together to kallisto, or quantified separately and combined later?
3. For human longitudinal samples, should DESeq2 use patient blocking or paired
   contrasts? The source reads `Patient` but currently fits `~group`.
4. Should human `Batch`, BMI, or other metadata enter the statistical design,
   visualization-only correction, or neither? Who approves covariates?
5. Is four samples per human group the intended scientific minimum, and is two
   per mouse group acceptable, or are these only operational guards?
6. Confirm contrast direction: the active human code estimates OD1 minus H and
   follow-up minus OD1; mouse code estimates the first label minus the second.
7. Is `RHFD vs HFD` the intended mouse intervention comparison? Documentation
   also contains `HFDvsRHCD`, while no `RHCD` group is parsed in active code.
8. Are `HFD`, `ICD`, `RHFD`, and `RICD` the complete current mouse group set?
9. Should tissue be a first-class manifest field rather than a general
   covariate? The current application leaves it in optional covariates until the
   data model is confirmed.
10. Which gene biotypes count as lncRNA? The current grep for `lncRNA` may exclude
    or include GENCODE categories differently across releases.

## References and methods

11. Confirm the exact compatible human genome, transcriptome, GTF, BioMart
    export, and release checksums for GENCODE v49.
12. Confirm the mouse GRCm39/vM38 resources; why is the annotation nested under a
    directory named `mouse_gencode_vM36`?
13. Must kallisto indexes be built per run, centrally cached, or supplied as
    reviewed reference bundles?
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
    and final projects live on Yan Lab workstations?

