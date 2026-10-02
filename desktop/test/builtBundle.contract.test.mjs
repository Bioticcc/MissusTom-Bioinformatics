import assert from "node:assert/strict";
import test from "node:test";
import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const distDirectory = fileURLToPath(new URL("../dist", import.meta.url));

async function builtSources() {
  const entries = await readdir(distDirectory, { recursive: true });
  const texts = await Promise.all(
    entries
      .filter((entry) => entry.endsWith(".js") || entry.endsWith(".html") || entry.endsWith(".css"))
      .map((entry) => readFile(path.join(distDirectory, entry), "utf8")),
  );
  return texts.join("\n");
}

test("built UI contains FASTA/GTF production wording and not human BioMart", async () => {
  const source = await builtSources();
  assert.match(source, /Transcriptome FASTA/);
  assert.match(source, /annotation GTF/i);
  assert.match(source, /Missus Tom will validate the FASTA and GTF/);
  assert.match(source, /Advanced: use an existing Kallisto index/);
  assert.doesNotMatch(source, /human BioMart/);
  assert.doesNotMatch(source, /human BioMart mapping/);
});
