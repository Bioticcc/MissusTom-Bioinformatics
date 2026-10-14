import { useState } from "react";

export type DirectoryOpenFailure = { path: string; message: string };

export function DirectoryOpenError({ path, message }: DirectoryOpenFailure) {
  const [copyStatus, setCopyStatus] = useState("");

  const copyPath = async () => {
    try {
      await navigator.clipboard.writeText(path);
      setCopyStatus("Path copied.");
    } catch {
      setCopyStatus("Copy failed. Select the path above to copy it.");
    }
  };

  return <div className="inline-error directory-open-error" role="alert">
    <p>{message}</p>
    <p>Directory: <code>{path}</code></p>
    <button type="button" className="text-button" onClick={() => void copyPath()}>Copy path</button>
    {copyStatus && <span role="status">{copyStatus}</span>}
  </div>;
}
