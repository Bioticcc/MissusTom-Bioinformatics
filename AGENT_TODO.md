# Minor backlog

These are deferred desktop polish items. The desktop UI owner should address
them without changing pipeline behavior or the local-only data boundary.

- Sidebar jitter while scrolling — Owner: desktop UI. Acceptance idea: scrolling
  long project/setup content leaves the sidebar width, position, and active
  state visually stable at common display scales.
- Native title bar is redundant and visually disconnected — Owner: desktop UI/
  Tauri host. Acceptance idea: remove the duplicated title treatment and carry
  the app background cleanly into the native title-bar region in packaged builds.
- Resolution and scaling polish — Owner: desktop UI. Acceptance idea: review
  supported minimum window size and 100%, 125%, 150%, and 200% scaling with no
  unusable controls or unexpected overflow.
- Clipped or overly sharp rounded corners — Owner: desktop UI. Acceptance idea:
  shell, panels, and overlays preserve intentional corner radii without clipped
  children or visible square seams.
- Tight container spacing — Owner: desktop UI. Acceptance idea: establish and
  apply readable spacing between adjacent panels and controls while preserving
  useful information density.
- Browser-only Open Project fallback — Owner: desktop UI/Tauri host. Lower
  priority; packaged Open Project now uses the app-owned Tauri dialog. Reassess
  only if browser-mode project selection remains a supported workflow.
