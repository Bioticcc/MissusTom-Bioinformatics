export interface SingleCellSeuratManifest {
  schema_version: "singlecell-seurat-v1";
  input: {
    seurat_rds: string;
    assay: string;
    metadata_columns: { sample_id: string; donor_id: string; condition: string; batch: string };
  };
  reference: {
    species: string;
    genome_build: string;
    mitochondrial_gene_ids: string[];
  };
  qc: { min_counts: number; min_features: number; max_features: number; max_mito_percent: number };
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

export function newSingleCellDraft(): SingleCellSeuratManifest {
  return {
    schema_version: "singlecell-seurat-v1",
    input: {
      seurat_rds: "",
      assay: "RNA",
      metadata_columns: { sample_id: "", donor_id: "", condition: "", batch: "" },
    },
    reference: { species: "", genome_build: "", mitochondrial_gene_ids: [] },
    qc: { min_counts: 500, min_features: 250, max_features: 6000, max_mito_percent: 20 },
    analysis: { normalization: "log_normalize", integration: "none", variable_features: 2000,
      pcs: 30, resolution: 0.5, seed: 42, cluster_markers: true },
  };
}
