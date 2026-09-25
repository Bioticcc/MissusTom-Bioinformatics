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

  return (
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
          onMouseDown={stopDrag}
          onClick={() => { void closeMainWindow(); }}
        >
          <span aria-hidden="true">×</span>
        </button>
      </div>
    </header>
  );
}
