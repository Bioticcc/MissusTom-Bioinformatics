import { getCurrentWindow } from "@tauri-apps/api/window";
import { useEffect, useState } from "react";
import {
  closeMainWindow,
  isDesktopShell,
  isMainWindowMaximized,
  minimizeMainWindow,
  startMainWindowDragging,
  toggleMaximizeMainWindow,
} from "../native";

export function TitleBar() {
  const [maximized, setMaximized] = useState(false);
  const [closing, setClosing] = useState(false);
  const [closeError, setCloseError] = useState("");

  useEffect(() => {
    if (!isDesktopShell()) return;
    let live = true;
    const sync = async () => {
      const next = await isMainWindowMaximized();
      if (live) setMaximized(next);
    };
    void sync();

    let unlisten: (() => void) | undefined;
    void getCurrentWindow().onResized(() => {
      void sync();
    }).then((dispose) => {
      if (live) unlisten = dispose;
      else dispose();
    });

    return () => {
      live = false;
      unlisten?.();
    };
  }, []);

  if (!isDesktopShell()) return null;

  const drag = (event: React.MouseEvent) => {
    if (event.button !== 0) return;
    void startMainWindowDragging().catch(() => {
      // Window chrome is best-effort; ignore drag failures outside the desktop shell.
    });
  };

  const stopDrag = (event: React.MouseEvent) => {
    event.stopPropagation();
  };

  const close = async () => {
    if (closing) return;
    setClosing(true);
    setCloseError("");
    try {
      await closeMainWindow();
    } catch (reason) {
      setClosing(false);
      setCloseError(reason instanceof Error ? reason.message : "Missus Tom could not stop safely.");
    }
  };

  return (
    <>
      <header className="app-titlebar" role="banner" aria-label="Window title bar">
      <div
        className="app-titlebar-drag"
        onMouseDown={drag}
        aria-label="Drag window"
      />
      <div className="app-titlebar-controls">
        <button
          type="button"
          className="app-titlebar-control"
          aria-label="Minimize window"
          onMouseDown={stopDrag}
          onClick={() => { void minimizeMainWindow(); }}
        >
          <span aria-hidden="true">−</span>
        </button>
        <button
          type="button"
          className="app-titlebar-control"
          aria-label={maximized ? "Restore window" : "Maximize window"}
          aria-pressed={maximized}
          onMouseDown={stopDrag}
          onClick={() => {
            void toggleMaximizeMainWindow().then(() => isMainWindowMaximized()).then(setMaximized);
          }}
        >
          <span aria-hidden="true">{maximized ? "❐" : "□"}</span>
        </button>
        <button
          type="button"
          className="app-titlebar-control app-titlebar-control-close"
          aria-label="Close window"
          disabled={closing}
          onMouseDown={stopDrag}
          onClick={() => { void close(); }}
        >
          <span aria-hidden="true">×</span>
        </button>
      </div>
      </header>
      {closing && <div className="shutdown-dialog" role="status" aria-live="polite">
        <strong>Stopping Missus Tom…</strong>
        <span>Active work is being safely stopped. This window will close automatically.</span>
      </div>}
      {closeError && <div className="shutdown-dialog shutdown-dialog-error" role="alert">
        <strong>Missus Tom is still running</strong>
        <span>{closeError}</span>
      </div>}
    </>
  );
}
