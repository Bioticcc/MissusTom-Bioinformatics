import type { MetadataCsvResult, ProposedSample } from "./types";

/** Replace imported design fields together and retain the original CSV identity. */
export function applyMetadataImport(samples: ProposedSample[], result: MetadataCsvResult): ProposedSample[] {
  const rows = new Map(result.rows.filter((row) => row.matched_sample_id)
    .map((row) => [row.matched_sample_id, row]));
  return samples.map((sample) => {
    const row = rows.get(sample.sample_id);
    if (!row) return sample;
    const covariates = { ...sample.covariates };
    delete covariates.intervention;
    if (row.intervention) covariates.intervention = row.intervention;
    return {
      ...sample,
      condition: row.condition,
      batch: row.batch,
      biological_replicate: row.biological_replicate ?? "",
      covariates,
      metadata_source_sample_id: row.source_sample_id ?? row.sample_id,
      metadata_source_path: result.path,
    };
  });
}
