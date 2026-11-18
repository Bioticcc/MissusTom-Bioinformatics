# SingleCell foundation: setup and teaching-method review

Executable files and the input/output contract are in
[`workflows/singlecell_rnaseq/START_HERE.md`](../../../workflows/singlecell_rnaseq/START_HERE.md).
This is a development workflow, not a supported desktop pipeline yet. Its input is
an existing Seurat object saved as `.rds`. See the
[active plan](../../exec-plans/active/singlecell-rnaseq.md).

## Setup ownership

Use a **separate** Micromamba environment, following Bulk's native-tool approach.
Do not add SingleCell packages to Bulk, ONT, backend Python or system R libraries.
The candidate [`environment.yaml`](../../../workflows/singlecell_rnaseq/environment.yaml)
uses conda-forge and bioconda with strict channel priority. Its ranges are not
an explicit lock and have not yet been resolved/installed here.

| Required runtime | Source / purpose |
| --- | --- |
| Python 3.11 | Standard-library validation and controlled Nextflow launch |
| Nextflow 24.04.4 + OpenJDK 17 | Same engine baseline as Bulk; local orchestration |
| R 4.4–4.5 | Isolated scientific runtime candidate |
| Seurat >=5.3,<6; SeuratObject >=5,<6 | v5 RNA layers, normalization, clustering, markers |
| Matrix >=1.6 | Sparse count validation and QC |
| ggplot2 >=3.5 | PDF figures |
| jsonlite >=1.8 | Typed manifest consumption |
| future >=1.34 | Explicit sequential execution; also a Seurat dependency |

Transitive packages such as uwot, Rcpp and BLAS come from the solver. Their exact
artifacts must be included in the generated lock. RStudio, Anaconda Navigator,
devtools, tidyverse, RCurl, plyr, reshape2, metap and online annotation downloads
are not needed by the implemented code. `slot="data"` remains the documented
FindMarkers API; layer-aware storage is used for Seurat v5 RNA objects.

Resolve, test package loading, and generate the Linux x86_64 explicit lock:

```bash
bash scripts/generate-singlecell-conda-lock.sh
micromamba create --yes --prefix /path/to/separate-singlecell-env \
  --file workflows/singlecell_rnaseq/singlecell-linux-64.lock
micromamba run --prefix /path/to/separate-singlecell-env \
  Rscript --vanilla workflows/singlecell_rnaseq/bin/check_dependencies.R
```

The first command downloads packages into a temporary environment, then exports
the solver's exact URLs/checksums. It does not prove scientific correctness.
The lock does **not** exist until that command succeeds; do not hand-write one.
The runtime is offline; provision the Nextflow engine cache during setup.
Before shipping: resolve the lock, run a synthetic complete Seurat fixture,
inspect resulting objects/figures, then add the verified lock to app Setup.
Native desktop execution remains **[Awaiting manual testing]**.

Validation on 2026-11-18 used a temporary environment with Seurat 5.5.1,
SeuratObject 5.4.0 and Nextflow 24.04.4. All 17 synthetic tests passed, including a
complete run on a split-layer object and rejection of unusable objects. No explicit
lock has been generated, and no real scientific data has been analyzed.

## What to retain and what to update

The downloaded repository is not uniformly old: its 2026 lessons already cover
Seurat v5, SCTransform and modern integration. These are targeted changes to a
teaching workflow, not a claim that all of its techniques are obsolete.

| Teaching pattern / location | Missus Tom decision |
| --- | --- |
| Lesson 03 loops over example directories and assigns example metadata | Read one Seurat object and require confirmed sample/donor/condition/batch columns; never infer biology from names. |
| Lesson 03 uses raw droplet matrices | The input object is expected to contain called cells. QC thresholds alone do not perform cell calling. |
| Lesson 05 example thresholds (500 counts, 250 genes, mitochondrial ratio 0.20), log10GenesPerUMI >0.80 | Require explicit cutoffs and retain before/after metrics. Do not generalize the example complexity ratio as a universal cutoff. Use clear 0–100 mitochondrial percentages. |
| Example mitochondrial symbol prefixes | Use explicit reference gene IDs; support mouse/human/other species without assuming symbol capitalization. |
| Lesson 07 SCTransform | Still current, not deprecated. Begin with an explicit LogNormalize baseline; add SCT v2 as a separately validated option with glmGamPoi. |
| Lesson 09 integration across example conditions | Keep integration off initially. A later opt-in batch correction needs confirmed technical covariates and confounding checks; never automatically remove the effect under study. |
| Older direct slot access and mixed v4/v5 examples | Use v5 assay layers and JoinLayers. Do marker tests on uncorrected RNA expression. |
| Cell-level marker tests in lesson 13 | Keep only exploratory cluster markers. Condition DE needs biological replicates, donor/pairing metadata and a pseudobulk model; cells are not independent donors. |
| Broad interactive install list, “update all”, unpinned GitHub Presto | Replace with a narrow isolated runtime plus generated exact lock. No interactive installs during an analysis. Presto is an optional performance addition requiring a pinned revision and parity check. |

Current primary documentation: [Seurat v5 layers](https://satijalab.org/seurat/articles/seurat5_essential_commands.html),
[integration](https://satijalab.org/seurat/articles/seurat5_integration.html),
[SCT v2](https://github.com/satijalab/seurat/blob/main/vignettes/sctransform_vignette.Rmd),
[marker testing and pseudobulk](https://satijalab.org/seurat/articles/de_vignette.html),
[FindMarkers API](https://satijalab.org/seurat/reference/findmarkers).

## Optional future packages: do not install indiscriminately

| Stage | Candidate | Admission requirement |
| --- | --- | --- |
| SCT v2 | sctransform, Bioconductor glmGamPoi | Matched R/Bioconductor release; normalization and DE assay tests |
| Doublet detection | Bioconductor scDblFinder, SingleCellExperiment | Per-capture/library boundaries, loading/chemistry assumptions, recorded scores and removal policy |
| Batch integration | Seurat built-in RPCA/CCA; harmony only if selected | Explicit batch covariates; uncorrected baseline; biological-signal review |
| Ambient RNA | SoupX or decontX, after design review | Suitable raw/filtered inputs and chemistry; correction is not universally required |
| Replicate-aware DE | DESeq2 (consistent with Bulk) or edgeR | Confirmed cell types, donor-level raw-count aggregation and full-rank paired/batch design |
| Automated annotation | SingleR plus a versioned local reference | Species/tissue-compatible references; confidence and provenance, never silent labels |

[Bioconductor installation guidance](https://bioconductor.org/install/) couples
package releases to R versions. Resolve optional tools as a coherent environment;
do not mix arbitrary current Bioconductor packages with an older R installation.
[scDblFinder documentation](https://bioconductor.org/packages/release/bioc/vignettes/scDblFinder/inst/doc/scDblFinder.html)
also records version-specific behavior, reinforcing the need for exact locks.

## Remaining application contracts

Before exposing a third pipeline: extend shared Pydantic/JSON Schema/TypeScript
manifests together; add adapter/registry and preflight; managed Setup installation
and version probes; Seurat object review in the wizard; artifact discovery and output gates;
Learn & Modify immutable source revisions; cancellation/containment and restart
policy; Linux packaging; scientific fixtures and native manual acceptance.
Keep Bulk and ONT defaults and environments unchanged throughout integration.
