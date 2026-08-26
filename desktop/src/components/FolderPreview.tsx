import type { DirectoryPreview } from "../types";

function formatBytes(bytes: number | null) {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GiB`;
}

export function FolderPreview({ label, preview }: { label: string; preview: DirectoryPreview }) {
  return (
    <section className="folder-preview" aria-label={`${label} folder contents`}>
      <header>
        <div>
          <strong>{label}</strong>
          <span>{preview.total_entries} items · {preview.total_files} files · {preview.total_directories} folders</span>
        </div>
        <code title={preview.directory}>{preview.directory}</code>
      </header>
      {preview.entries.length === 0 ? (
        <p className="folder-empty">Folder is empty.</p>
      ) : (
        <div className="folder-file-list" role="table" aria-label={`${label} file list`}>
          <div className="folder-file-heading" role="row">
            <span role="columnheader">Name</span><span role="columnheader">Type</span><span role="columnheader">Size</span>
          </div>
          {preview.entries.map((entry) => (
            <div className="folder-file-row" role="row" key={`${entry.kind}:${entry.name}`}>
              <span role="cell" title={entry.name}>{entry.kind === "directory" ? "▸ " : ""}{entry.name}</span>
              <span role="cell">{entry.file_type}</span>
              <span role="cell">{entry.kind === "file" ? formatBytes(entry.size_bytes) : "—"}</span>
            </div>
          ))}
        </div>
      )}
      {preview.truncated && <small>Showing the first {preview.entries.length} items.</small>}
    </section>
  );
}
