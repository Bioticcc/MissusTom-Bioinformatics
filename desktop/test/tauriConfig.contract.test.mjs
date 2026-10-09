import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const tauriConfig = JSON.parse(
  await readFile(new URL("../src-tauri/tauri.conf.json", import.meta.url), "utf8"),
);
const packageJson = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
const releaseConfig = JSON.parse(
  await readFile(new URL("../src-tauri/tauri.release.conf.json", import.meta.url), "utf8"),
);

// Tauri 2's documented `bundle.category` values. Keep this list aligned with
// https://v2.tauri.app/reference/config/#bundleconfig.category.
const TAURI_BUNDLE_CATEGORIES = new Set([
  "Business",
  "DeveloperTool",
  "Education",
  "Entertainment",
  "Finance",
  "Game",
  "ActionGame",
  "AdventureGame",
  "ArcadeGame",
  "BoardGame",
  "CardGame",
  "CasinoGame",
  "DiceGame",
  "EducationalGame",
  "FamilyGame",
  "KidsGame",
  "MusicGame",
  "PuzzleGame",
  "RacingGame",
  "RolePlayingGame",
  "SimulationGame",
  "SportsGame",
  "StrategyGame",
  "TriviaGame",
  "WordGame",
  "GraphicsAndDesign",
  "HealthcareAndFitness",
  "Lifestyle",
  "Medical",
  "Music",
  "News",
  "Photography",
  "Productivity",
  "Reference",
  "SocialNetworking",
  "Sports",
  "Travel",
  "Utility",
  "Video",
  "Weather",
]);

const mainWindow = tauriConfig.app.windows[0];

test("Tauri bundle category is a documented Tauri 2 value", () => {
  assert.ok(
    TAURI_BUNDLE_CATEGORIES.has(tauriConfig.bundle.category),
    `Unsupported Tauri bundle category: ${tauriConfig.bundle.category}`,
  );
});

test("Main window uses frameless chrome with supported minimum size", () => {
  assert.equal(mainWindow.decorations, false);
  assert.equal(mainWindow.minWidth, 760);
  assert.equal(mainWindow.minHeight, 520);
  assert.equal(mainWindow.title, "Missus Tom");
});

test("local release builds inject the git revision used by frozen backend sidecars", () => {
  assert.match(packageJson.scripts["tauri:release"], /VITE_BUILD_REVISION/);
  assert.match(packageJson.scripts["tauri:release"], /git rev-parse HEAD/);
});

test("release package includes the backend build revision beside its runtime resources", () => {
  assert.equal(
    releaseConfig.bundle.resources["../../backend/build/sidecar-resources/build_revision.txt"],
    "resources/build_revision.txt",
  );
});
