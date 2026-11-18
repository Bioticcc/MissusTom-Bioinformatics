# Empty contigs in Stage 04 Modkit statistics

The Nov 2 15:23 run passed the repaired Modkit summary and emitted 3,849,643
pileup rows. Our summary validator then incorrectly required a stats row for
every FAI contig. Modkit stats omits contigs absent from bedMethyl, including
contigs with reference CpGs but no observed calls.

The validator now permits an omitted row only when the complete validated
bedMethyl aggregation contains no coordinates for that contig. Missing stats
for an observed coordinate, including a zero-valid-call coordinate, still fail.
All FAI contigs and reference CpG denominators remain in output; zero valid-call
rates remain NA. No rows or reads are dropped to bypass validation.

Verification: 42 workflow tests ran, 41 passed and one optional stock-binary
comparison skipped. Real-tool Stage 04 fixtures cover empty CpG and no-CpG
contigs in both measurement modes. The full failed-run pileup was summarized
successfully into /tmp/ont-empty-contigs-validation: 195 contigs retained, 25
verified empty bedMethyl contigs. The actual annotation-free core R report
completed and generated four PDFs and HTML. Scoped lint/format/diff checks pass.
The complete multi-sample app rerun remains an operator acceptance step.
