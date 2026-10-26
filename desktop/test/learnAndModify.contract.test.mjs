import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const editor = await readFile(new URL("../src/components/SourceEditor.tsx", import.meta.url), "utf8");
const screen = await readFile(new URL("../src/screens/LearnAndModify.tsx", import.meta.url), "utf8");
const settings = await readFile(new URL("../src/screens/Settings.tsx", import.meta.url), "utf8");
const wizard = await readFile(new URL("../src/screens/NewProjectWizard.tsx", import.meta.url), "utf8");

test("Learn and Modify uses CodeMirror with read-only and editing states", () => {
  assert.match(screen, /Dev here! Files are currently not formatted/);
  assert.match(editor, /basicSetup/);
  assert.match(editor, /EditorState\.readOnly/);
  assert.match(editor, /python\(\)/);
  assert.match(editor, /StreamLanguage\.define\(groovy\)/);
  assert.match(editor, /StreamLanguage\.define\(r\)/);
  assert.match(editor, /StreamLanguage\.define\(shell\)/);
  assert.match(screen, /I Understand/);
  assert.match(screen, /Permanent data loss/);
  assert.match(screen, /button primary/);
  assert.match(screen, /run-mode-option/);
  assert.match(screen, /Modified by user/);
  assert.match(screen, /All new and existing projects/);
  assert.match(wizard, /Modified pipeline selected/);
  assert.match(wizard, /next run for this project will use user-modified code/);
  assert.doesNotMatch(screen, /learn-introduction/);
  assert.match(screen, /Save Changes/);
  assert.match(screen, /Discard them/);
  assert.match(screen, /Output_Log_Key\.md/);
  assert.match(screen, /cannot be modified/);
});

test("Settings gates guided Debian uninstall behind exact confirmation", () => {
  assert.match(settings, /UNINSTALL MISSUS TOM/);
  assert.match(settings, /getUninstallStatus/);
  assert.match(settings, /isRunActive \|\| !uninstall\.supported/);
  assert.match(settings, /Proceed to Uninstall/);
  assert.match(settings, /button primary/);
  assert.match(settings, /warning-actions/);
  assert.match(settings, /Restored successfully/);
  assert.match(settings, /restore-pipelines-status/);
  assert.match(settings, /Command copied to your clipboard/);
  assert.match(settings, /The command could not be copied automatically/);
  assert.match(settings, /Uninstall command ready/);
});
