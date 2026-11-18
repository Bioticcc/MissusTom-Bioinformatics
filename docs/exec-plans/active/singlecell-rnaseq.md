# SingleCell RNA-seq foundation

## Decision: 2026-11-18

SingleCell analysis takes one existing Seurat object saved as `.rds`. This replaces
the FASTQ and count-matrix inputs. That earlier code remains in git history at commit
`1ef42ae`.

## Input contract (`singlecell-seurat-v1`)

- Raw integer counts come from a named assay's `counts` layer. Split v5 layers are
  joined. SCT-only, normalized-only and on-disk count matrices are rejected.
- The user names the sample, donor, condition and batch metadata columns.
- Normalization, variable features, PCA, clustering and UMAP are always recomputed.
  Earlier reductions and clusters are not reused. Earlier metadata is kept with an
  `input_` prefix. The input file is never modified.
- One explicit set of QC cutoffs applies to all cells.

## Validation

17 synthetic tests passed on 2026-11-18 in a temporary environment with Seurat 5.5.1,
SeuratObject 5.4.0 and Nextflow 24.04.4, including a complete run on a split-layer
object. Real-data scientific acceptance and native GUI acceptance are still pending.

## Remaining product gates

Resolved explicit environment lock and isolated install; real-data scientific
validation; integration, doublet and ambient-RNA decisions; shared
manifest/schema/TypeScript, adapter, preflight, Setup, wizard, artifact discovery,
source revisions, containment, packaging, and native manual acceptance. Keep the
pipeline out of the application registry until those contracts are implemented.
