import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const styles = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");

test("Desktop shell contains scrolling in the main pane", () => {
  assert.match(styles, /\.desktop-root\s*\{[\s\S]*height:\s*100vh[\s\S]*overflow:\s*hidden/);
  assert.match(
    styles,
    /\.desktop-root \.main-content\s*\{[\s\S]*overflow-y:\s*auto[\s\S]*scrollbar-gutter:\s*stable/,
  );
  assert.match(
    styles,
    /\.desktop-root \.sidebar\s*\{[\s\S]*position:\s*static[\s\S]*scrollbar-gutter:\s*stable/,
  );
});

test("Narrow and short windows retain usable navigation", () => {
  assert.match(styles, /@media \(max-height: 650px\) and \(min-width: 781px\)/);
  assert.match(
    styles,
    /@media \(max-width: 780px\)[\s\S]*\.desktop-root \.app-shell[\s\S]*flex-direction:\s*column/,
  );
  assert.match(styles, /\.header-actions \.button,[\s\S]*flex:\s*1 1 12rem/);
});

test("Panels use shared spacing, radius, and border tokens", () => {
  assert.match(styles, /--line:\s*#dce5e1/);
  assert.match(styles, /--radius-panel:\s*14px/);
  assert.match(styles, /--space-4:\s*1\.35rem/);
  assert.match(
    styles,
    /\.panel,[\s\S]*border-radius:\s*var\(--radius-panel\)[\s\S]*background-clip:\s*padding-box/,
  );
  assert.match(styles, /\.page-stack\s*\{[\s\S]*gap:\s*var\(--space-4\)/);
});
