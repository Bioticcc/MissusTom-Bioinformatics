import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const titleBarSource = await readFile(new URL("../src/components/TitleBar.tsx", import.meta.url), "utf8");
const nativeSource = await readFile(new URL("../src/native.ts", import.meta.url), "utf8");
const appSource = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");
const stylesSource = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");
const defaultCapability = JSON.parse(
  await readFile(new URL("../src-tauri/capabilities/default.json", import.meta.url), "utf8"),
);

test("Frameless title bar is desktop-only and exposes window controls", () => {
  assert.match(titleBarSource, /if \(!isDesktopShell\(\)\) return null/);
  assert.match(titleBarSource, /className="app-titlebar-drag"[\s\S]*onMouseDown=\{drag\}/);
  assert.match(titleBarSource, /aria-label="Window title bar"/);
  assert.match(titleBarSource, /aria-label="Drag window"/);
  assert.match(titleBarSource, /aria-label="Minimize window"/);
  assert.match(titleBarSource, /aria-label=\{maximized \? "Restore window" : "Maximize window"\}/);
  assert.match(titleBarSource, /aria-label="Close window"/);
  assert.match(titleBarSource, /startMainWindowDragging/);
  assert.match(titleBarSource, /minimizeMainWindow/);
  assert.match(titleBarSource, /toggleMaximizeMainWindow/);
  assert.match(titleBarSource, /closeMainWindow/);
  assert.doesNotMatch(titleBarSource, /<h1[^>]*>Missus Tom<\/h1>/);
});

test("Native helpers back the integrated title bar", () => {
  assert.match(nativeSource, /export async function startMainWindowDragging\(\)/);
  assert.match(nativeSource, /export async function minimizeMainWindow\(\)/);
  assert.match(nativeSource, /export async function toggleMaximizeMainWindow\(\)/);
  assert.match(nativeSource, /export async function closeMainWindow\(\)/);
  assert.match(nativeSource, /export async function isMainWindowMaximized\(\)/);
  assert.match(nativeSource, /getCurrentWindow\(\)\.toggleMaximize\(\)/);
  assert.match(nativeSource, /getCurrentWindow\(\)\.close\(\)/);
  assert.doesNotMatch(nativeSource, /getCurrentWindow\(\)\.destroy\(\)/);
  assert.match(nativeSource, /if \(!isDesktopShell\(\)\)/);
});

test("App mounts the title bar once above the shell without duplicate product branding", () => {
  assert.match(appSource, /import \{ TitleBar \} from "\.\/components\/TitleBar"/);
  assert.match(appSource, /className=\{isDesktopShell\(\) \? "desktop-root" : undefined\}/);
  assert.match(appSource, /<TitleBar \/>/);
  assert.doesNotMatch(appSource, /<title>Missus Tom<\/title>/);
  assert.doesNotMatch(titleBarSource, />Missus Tom</);
  assert.match(stylesSource, /\.app-titlebar/);
  assert.match(stylesSource, /\.desktop-root/);
});

test("Main window capability set grants only required window chrome permissions", () => {
  const required = [
    "core:window:allow-start-dragging",
    "core:window:allow-minimize",
    "core:window:allow-toggle-maximize",
    "core:window:allow-close",
    "core:window:allow-is-maximized",
  ];
  for (const permission of required) {
    assert.ok(defaultCapability.permissions.includes(permission), `Missing ${permission}`);
  }
  assert.ok(!defaultCapability.permissions.includes("core:window:default"));
});
