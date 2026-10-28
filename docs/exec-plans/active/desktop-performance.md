# Desktop performance investigation

Issue: first high-priority item in `AGENT_TODO.md`. Do not mark it complete until native Linux and WSL2 measurements show a user-facing improvement.

## Reproducible baseline (2026-10-14)

- Source review found that each Jobs refresh supplied a new `fetchChunk` function to every `LiveCommandLog`. Its effect depended on that function, so a refresh restarted each log request, including all expanded historical logs. Historical logs started expanded.
- Every log had a one-second clock render, including terminal logs. The complete accumulated log text was placed in `<pre>` on each render.
- Rendering a synthetic 2.1 million character log with React `renderToStaticMarkup` took 6.32 ms median over 11 warmed runs. Rendering the last 131,072 characters took 0.35 ms. This is a text rendering proxy, not an end-to-end WebKit frame measurement. Reproduce from `desktop/` using the following command:
- Repeating the same proxy after the change measured 6.30 ms for the full string and 0.36 ms for the 131,072-character preview. Timing variability is expected; the reduction in rendered characters is the meaningful comparison.

```bash
node --input-type=module -e 'import React from "react"; import { renderToStaticMarkup } from "react-dom/server"; import { performance } from "node:perf_hooks"; const log = "[nextflow] process output <>&\n".repeat(70000); for (const [name, value] of [["full",log],["preview",log.slice(-131072)]]) { const samples=[]; for(let i=0;i<12;i++){const begin=performance.now();renderToStaticMarkup(React.createElement("pre",null,value));samples.push(performance.now()-begin)} samples.shift(); console.log(JSON.stringify({name,characters:value.length,median_ms:samples.sort((a,b)=>a-b)[Math.floor(samples.length/2)].toFixed(2)})); }'
```

## Current changes

- Keep the polling effect stable when callers recreate the fetch function. Skip polling closed logs and stop the one-second clock for terminal logs.
- Start finished Jobs logs closed. Show at most 131,072 recent characters while retaining all loaded text for Copy and Save.
- Frontend lint, typecheck, complete `npm test` (57 passed, none failed or skipped), and production `npm run build` passed after the final edit.
- Settings now provides a state-labelled diagnostics recorder with a configurable in-app start/stop shortcut. It writes timestamped NDJSON samples below the application's local data directory and records app/WebKit process-tree CPU/RAM, packaged-backend CPU/RAM, local health latency, platform/WSL context, and NVIDIA-driver presence. It never changes projects or workflows. The resulting path is shown after stopping.

## Remaining validation

- On native Linux and WSL2, record the actual Missus Tom WebKit renderer, whether hardware or software rendering is in use, app/WebKit CPU and memory, and GPU activity. WebKitGTK documents `webkit://gpu/stdout` for graphics reports ([WebKitGTK release](https://webkitgtk.org/2024/09/02/webkitgtk2.45.92-released.html)); Mesa documents `glxinfo` for the OpenGL renderer ([Mesa FAQ](https://docs.mesa3d.org/faq.html)). The latter reports the display's OpenGL renderer, not proof of the renderer chosen by this WebKit view. This checkout has an NVIDIA RTX 4060 driver, WebKitGTK 2.50.6, and Mesa 22.3.6, but no running Missus Tom process, `glxinfo`, or `eglinfo`; it cannot establish the app renderer. Do not force a renderer from startup warnings alone.
- Measure navigation time, scroll frame behavior, API latency, and resource use before and after this patch on both platforms, during idle use, validation, an active run, and large log output. Preserve scientific inputs and active runs. Compare the same workload and log size.
- Inspect the backend only if API timing or resource measurements implicate it. Run the final non-destructive suite after the complete backlog work.
- Manually verify the Settings control, shortcut, output path, and report contents in the packaged Linux and WSL2 applications before treating the recorder itself as accepted.
