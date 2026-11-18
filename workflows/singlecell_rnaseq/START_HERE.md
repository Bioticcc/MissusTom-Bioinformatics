# Start here: SingleCell RNA-seq

Development foundation. In the desktop app, open **New project → Pipeline →
SingleCell RNA-seq** to choose a Seurat object and export a standalone
configuration. Managed Setup installation, saving as an app project and running
from the app are not available yet. The analysis still needs an isolated
environment and scientific validation on real data.

## What this increment does

Starts with **one existing Seurat object saved as `.rds`**. The workflow reads the
object's raw counts and your confirmed metadata columns, applies explicit cell QC,
then runs Seurat v5 LogNormalize, variable-feature selection, scaling, PCA, Louvain
clustering and UMAP. Optional Wilcoxon cluster markers are exploratory. All analysis
runs locally; it does not download references or install packages during execution.

Objects that were already analyzed are supported. Earlier normalization, scaling,
reductions and clusters are **not reused**: every result is recomputed from raw
counts. Earlier cell metadata is kept in columns prefixed `input_`, so a previous
`seurat_clusters` becomes `input_seurat_clusters`. The input file is never modified.

Doublet removal, ambient-RNA correction, integration, cell-type annotation and
donor-aware condition testing are future stages. It can analyze one or multiple
samples. No species, tissue or condition is fixed.

## How the files connect

1. `run_pipeline.py` validates the standalone manifest and `.rds` signature, hashes
   the object and sources, creates a new run directory and starts Nextflow.
2. `main.nf` is the pipeline orchestrator. It stages the object and invokes the R
   analysis.
3. `nextflow.config` owns reports and the local profile;
   `conf/resources.config` owns task resource requests.
4. `bin/import_qc.R` reads the object and computes explicit QC metrics.
5. `bin/singlecell_analysis.R` performs the analysis and publishes artifacts.
6. `bin/check_dependencies.R` checks the isolated R installation without changing it.

This standalone `singlecell-seurat-v1` contract is separate from the desktop's
`ProjectManifest`. Registering it requires coordinated backend/schema/UI work.
Only the supplied Python runner is the supported development entry point.

## Inputs and generality rules

Copy `example_manifest.json` outside the source tree and replace its placeholders.
Its QC values are examples, **not recommended biological defaults**.

- `seurat_rds` is one Seurat object written by `saveRDS()`. Opening an `.rds` file can
  run code stored inside it, so only use objects from sources you trust.
- `assay` names the assay holding raw counts, usually `RNA`. Its `counts` layer must
  contain finite nonnegative integers. Split v5 layers are joined automatically.
  SCT-only, normalized-only and on-disk (BPCells) count matrices are rejected.
- `metadata_columns` names the object's columns for `sample_id`, `donor_id`,
  `condition` and `batch`. Every cell needs a value in each. Columns are never guessed.
- Explicitly declare species and genome build **and annotation release**. These
  labels record your declaration, not independently verified provenance.
- Supply mitochondrial feature **IDs** exactly as named in the object. Human/mouse
  symbol prefixes are not assumed. Missing IDs are errors, rather than a false 0% pass.
- Set `min_counts`, `min_features`, `max_features` and `max_mito_percent` explicitly.
  They apply to all cells. All cutoffs are inclusive; mitochondrial values are
  percentages from 0 to 100. Empty cells always fail QC. A sample with fewer than three
  retained cells fails the run.
- PCs, variable-feature count, resolution, random seed and marker option are
  explicit. Too few cells or variable genes for the selected PCs is an error;
  the pipeline does not silently change the analysis.
- Integration is `none`. Review sample/batch UMAPs for technical structure before
  interpreting clusters. No automatic regression of condition, cell cycle or QC.

Python checks the manifest and file signature; complete object validation happens in R.

## Setup and execution

See [the setup and method review](../../docs/workflows/singlecell_rnaseq/README.md)
for package sources, optional tools, and the environment lock gate.
With the isolated environment activated:

```bash
python workflows/singlecell_rnaseq/run_pipeline.py --manifest /path/manifest.json --check-only
python workflows/singlecell_rnaseq/run_pipeline.py --manifest /path/manifest.json \
  --run-dir /path/new-singlecell-run --cpus 2 --memory-gb 8
```

Check-only neither runs R nor opens the object. Execution requires a new run
directory and a locally cached Nextflow engine (`-offline`); it never overwrites
an earlier run. There is no supported resume command yet. Retained `work/` files
are for diagnosis. Native Nextflow resource settings are scheduler requests;
desktop aggregate containment/cancellation is a separate integration gate.

## Synthetic checks

```bash
python3 -m unittest discover -s workflows/singlecell_rnaseq/tests -v
SINGLECELL_TEST_NEXTFLOW=1 python3 -m unittest discover -s workflows/singlecell_rnaseq/tests -v
# Activate the isolated Seurat environment before enabling the full analysis:
SINGLECELL_TEST_SEURAT=1 python3 -m unittest discover -s workflows/singlecell_rnaseq/tests -v
```

The normal checks run validation and QC boundaries using Matrix when R is installed.
The Nextflow option tests staging/publication with a replacement R command. The
Seurat option runs the supported runner on a synthetic split-layer object, confirms
the input file is unchanged, and checks raw counts, metadata and reductions.

## Results

- `results/qc/`: all input-cell metrics, retained flags, per-sample cell totals.
- `results/tables/`: feature annotations, retained cell metadata, marker status,
  and optional `exploratory_cluster_markers.tsv`.
- `results/figures/`: UMAPs by cluster/sample/condition/batch, retained-cell QC,
  PCA elbow plot. Inspect the all-cell QC table as well as retained-cell plots.
- `results/objects/singlecell.rds`: RNA counts, normalized data, metadata,
  reductions and clusters.
- `results/tables/provenance/`: resolved manifest, SHA-256 input/source hashes,
  R session, installed versions, settings and explicit unperformed stages.
- `reports/`: Nextflow report, trace and timeline. `nextflow.log` and `work/`
  retain execution details. A failed run can leave partial artifacts; success
  requires the runner to exit zero, not simply the presence of a results folder.

Cluster markers do not establish treatment effects. Condition testing must use
donor-aware replicate designs, ordinarily pseudobulk within confirmed cell types,
with appropriate batch/pairing checks similar to Bulk.

## Teaching source and attribution

Scientific teaching basis: [HBC Training, Intro-to-scRNAseq](https://github.com/hbctraining/Intro-to-scRNAseq),
local snapshot commit `58724dcd976eae78c4c858fe29ba936a0a8aedd0` (2026-08-20).
Lessons 03 (loading), 05 (QC), 07 (normalization), 09 (integration review),
10–11 (clustering/QC), and 13 (markers) informed this implementation.
The reviewed lessons declare [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Credit their listed authors: Mary Piper, Meeta Mistry, Radhika Khetani,
Lorena Pantano, Jihe Liu, Will Gammerdinger, Noor Sohail and Amélie Julé.
This is a new automated implementation, with the changes documented in the method
review; the teaching repository and its datasets remain untouched.
