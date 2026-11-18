import chemistryCatalog from "../../workflows/singlecell_rnaseq/chemistries.json";

export const singleCellChemistries = chemistryCatalog;

export interface SingleCellLibrary {
  sample_id: string;
  donor_id: string;
  condition: string;
  batch: string;
  chemistry: string;
  material: string;
  counting_mode: string;
  barcode_whitelist: string;
  expected_cells: number;
  lanes: Array<{ r1: string; r2: string }>;
  qc: { min_counts: number; min_features: number; max_features: number; max_mito_percent: number };
}

export interface SingleCellFastqManifest {
  schema_version: "singlecell-fastq-v1";
  reference: {
    species: string;
    genome_build: string;
    mitochondrial_gene_ids: string[];
    fasta: string;
    gtf: string;
    sjdb_overhang: number;
    sa_index_n_bases: number;
  };
  samples: SingleCellLibrary[];
  analysis: {
    normalization: "log_normalize";
    integration: "none";
    variable_features: number;
    pcs: number;
    resolution: number;
    seed: number;
    cluster_markers: boolean;
  };
}

export function newSingleCellLibrary(sampleId: string): SingleCellLibrary {
  return {
    sample_id: sampleId, donor_id: "", condition: "", batch: "", chemistry: "unknown",
    material: "unknown", counting_mode: "unknown", barcode_whitelist: "", expected_cells: 3000,
    lanes: [{ r1: "", r2: "" }],
    qc: { min_counts: 500, min_features: 250, max_features: 6000, max_mito_percent: 20 },
  };
}

export function newSingleCellDraft(): SingleCellFastqManifest {
  return {
    schema_version: "singlecell-fastq-v1",
    reference: { species: "", genome_build: "", mitochondrial_gene_ids: [], fasta: "", gtf: "",
      sjdb_overhang: 99, sa_index_n_bases: 14 },
    samples: [newSingleCellLibrary("sample-1")],
    analysis: { normalization: "log_normalize", integration: "none", variable_features: 2000,
      pcs: 30, resolution: 0.5, seed: 42, cluster_markers: true },
  };
}

export function nextSingleCellLibraryId(samples: SingleCellLibrary[]): string {
  let index = 1;
  while (samples.some((sample) => sample.sample_id === `sample-${index}`)) index++;
  return `sample-${index}`;
}
