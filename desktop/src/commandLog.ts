import type { CommandLogChunk } from "./types";

export const LOG_PREVIEW_CHARACTERS = 131_072;
export const CLIPBOARD_LOG_BYTES = 8 * 1024 * 1024;

export function appendLogTail(previous: string, chunk: string): string {
  return (previous + chunk).slice(-LOG_PREVIEW_CHARACTERS);
}

/** Fetch only on Copy; bound even this temporary clipboard allocation. */
export async function readClipboardLog(
  fetchChunk: (offset: number, signal: AbortSignal) => Promise<CommandLogChunk>,
  signal: AbortSignal,
): Promise<string> {
  let offset = 0;
  let end: number | undefined;
  const chunks: string[] = [];
  do {
    const chunk = await fetchChunk(offset, signal);
    end ??= chunk.bytes_available;
    if (end > CLIPBOARD_LOG_BYTES || chunk.bytes_available > CLIPBOARD_LOG_BYTES) {
      throw new Error("This log is too large for clipboard export. Use Save for the complete log.");
    }
    chunks.push(chunk.text);
    if (chunk.next_offset <= offset && offset < end) throw new Error("The log changed while copying. Retry Copy.");
    offset = chunk.next_offset;
  } while (offset < end);
  return chunks.join("");
}
