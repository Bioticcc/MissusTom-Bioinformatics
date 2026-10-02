import type { ProposedSample } from "./types";

export interface AutomaticSettingSuggestion {
  sampleIndex: number;
  condition?: string;
  biological_replicate?: string;
  batch?: string;
  intervention?: string;
}

export interface AutomaticSettingsResult {
  suggestions: AutomaticSettingSuggestion[];
  warnings: string[];
  inferredFields: Array<"condition" | "biological_replicate" | "batch" | "intervention">;
}

const technicalTokens = new Set([
  "abundance", "bam", "fastq", "fq", "gz", "gzip", "lane", "read", "r1", "r2", "s1", "s2", "tsv",
]);
const genericTokens = new Set(["input", "sample", "samples", "seq", "sequencing"]);
const markerPrefixes = ["replicate", "rep", "biological", "bio", "batch", "run", "intervention", "treatment", "drug", "dose", "vehicle"];

function sourceText(sample: ProposedSample): string {
  return [sample.sample_id, ...sample.r1_files, ...sample.r2_files, ...sample.ont_bam_files, sample.abundance_tsv ?? ""]
    .map((value) => value.split(/[\\/]/).pop() ?? value)
    .join(" ");
}

function tokens(sample: ProposedSample): string[] {
  return sourceText(sample)
    .replace(/\.(fastq|fq|gz|bam|tsv)(?=$|\s)/gi, " ")
    .split(/[_\-.\s]+/)
    .map((token) => token.trim())
    .filter((token) => token && !technicalTokens.has(token.toLowerCase()) && !/^l\d{3}$/i.test(token) && !/^i[12]$/i.test(token));
}

function conditionTokens(sample: ProposedSample): string[] {
  const result: string[] = [];
  const raw = tokens(sample);
  for (let index = 0; index < raw.length; index += 1) {
    const lower = raw[index].toLocaleLowerCase();
    if (markerPrefixes.some((prefix) => lower === prefix || (lower.startsWith(prefix) && lower.length > prefix.length))) {
      if (lower === "replicate" || lower === "rep" || lower === "biological" || lower === "bio" || lower === "batch" || lower === "run" || lower === "intervention" || lower === "treatment" || lower === "drug" || lower === "dose") index += 1;
      continue;
    }
    if (!genericTokens.has(lower)) result.push(raw[index]);
  }
  return result;
}

function markerValue(text: string, markers: string[]): string | undefined {
  const parts = text.split(/[_\-.\s]+/).filter(Boolean);
  for (let index = 0; index < parts.length; index += 1) {
    const token = parts[index];
    const lower = token.toLocaleLowerCase();
    for (const marker of markers) {
      if (lower === marker) {
        if (marker === "vehicle") return token;
        return parts[index + 1];
      }
      if (lower.startsWith(marker) && token.length > marker.length) return token.slice(marker.length);
    }
  }
  return undefined;
}

function canonicalValues(values: string[]): Map<string, string> {
  const result = new Map<string, string>();
  for (const value of values) {
    const key = value.toLocaleLowerCase();
    if (!result.has(key)) result.set(key, value);
  }
  return result;
}

function varyingToken(samples: ProposedSample[], tokenLists: string[][]): Map<number, string> | null {
  const maxLength = Math.max(0, ...tokenLists.map((list) => list.length));
  for (let position = 0; position < maxLength; position += 1) {
    const values = tokenLists.map((list) => list[position]).filter(Boolean);
    const unique = canonicalValues(values);
    if (unique.size < 2 || values.length < samples.length) continue;
    const candidate = new Map<number, string>();
    tokenLists.forEach((list, index) => candidate.set(index, unique.get(list[position].toLocaleLowerCase()) ?? list[position]));
    return candidate;
  }
  return null;
}

export function inferAutomaticSettings(samples: ProposedSample[]): AutomaticSettingsResult {
  const included = samples
    .map((sample, sampleIndex) => ({ sample, sampleIndex }))
    .filter(({ sample }) => sample.included);
  if (included.length === 0) {
    return { suggestions: [], warnings: ["Include at least one sample before attempting automatic settings."], inferredFields: [] };
  }

  const rawText = included.map(({ sample }) => sourceText(sample));
  const tokenLists = included.map(({ sample }) => conditionTokens(sample));
  const conditionValues = varyingToken(included.map(({ sample }) => sample), tokenLists);
  const suggestions = new Map<number, AutomaticSettingSuggestion>();
  const inferredFields = new Set<AutomaticSettingsResult["inferredFields"][number]>();
  const warnings: string[] = [];

  const suggestionFor = (sampleIndex: number) => {
    const existing = suggestions.get(sampleIndex) ?? { sampleIndex };
    suggestions.set(sampleIndex, existing);
    return existing;
  };

  if (conditionValues) {
    conditionValues.forEach((condition, includedIndex) => {
      suggestionFor(included[includedIndex].sampleIndex).condition = condition;
    });
    inferredFields.add("condition");
  } else {
    warnings.push("No unambiguous repeated condition pattern was found in the filenames.");
  }

  const explicitReplicates = rawText.map((text) => markerValue(text, ["replicate", "rep", "biological", "bio"]));
  const explicitBatches = rawText.map((text) => markerValue(text, ["batch", "run"]));
  const explicitInterventions = rawText.map((text) => markerValue(text, ["intervention", "treatment", "drug", "dose", "vehicle"]));

  if (explicitReplicates.every(Boolean)) {
    explicitReplicates.forEach((replicate, index) => { suggestionFor(included[index].sampleIndex).biological_replicate = replicate; });
    inferredFields.add("biological_replicate");
  } else if (conditionValues) {
    const numericReplicates = tokenLists.map((list) => [...list].reverse().find((token: string) => /^\d{1,3}$/.test(token)));
    if (numericReplicates.every(Boolean) && new Set(numericReplicates).size > 1) {
      numericReplicates.forEach((replicate, index) => { suggestionFor(included[index].sampleIndex).biological_replicate = replicate; });
      inferredFields.add("biological_replicate");
    } else {
      warnings.push("No consistent biological-replicate marker was found in the filenames.");
    }
  }

  if (explicitBatches.every(Boolean)) {
    explicitBatches.forEach((batch, index) => { suggestionFor(included[index].sampleIndex).batch = batch; });
    inferredFields.add("batch");
  }
  if (explicitInterventions.every(Boolean)) {
    explicitInterventions.forEach((intervention, index) => { suggestionFor(included[index].sampleIndex).intervention = intervention; });
    inferredFields.add("intervention");
  }

  if (!inferredFields.size) warnings.push("No automatic settings could be proposed from these filenames.");
  return { suggestions: [...suggestions.values()], warnings, inferredFields: [...inferredFields] };
}
