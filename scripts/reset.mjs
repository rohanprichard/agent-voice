#!/usr/bin/env node
// Reset the local app so first-run setup happens again.
//
//   npm run reset
//
// Clears the saved speech settings and the onboarding progress that lives in
// renderer storage. Downloaded models and the local token are kept, so nothing
// is re-downloaded. A copy of what was removed is written next to the data
// directory before anything is deleted.
//
// The app has to be closed first: Electron rewrites its storage as it exits, so
// clearing it underneath a running app would silently undo the reset.

import { execFileSync } from "node:child_process";
import { cpSync, existsSync, lstatSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const port = Number(process.env.TALKTOME_PORT || 8765);

// These carry setup state. Everything else in the directory is either a cache
// or something we must keep.
const CLEARED = ["settings.json", "Local Storage", "Session Storage"];

function dataDir() {
  if (process.env.TALKTOME_DATA_DIR) return process.env.TALKTOME_DATA_DIR;
  const python = path.join(
    root,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  if (!existsSync(python)) throw new Error("Run `uv sync` first: the local Python is missing.");
  return execFileSync(python, ["-c", "from talktome.config import data_dir; print(data_dir())"], {
    cwd: root,
    encoding: "utf8",
  }).trim();
}

async function running() {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/v1/health`, {
      signal: AbortSignal.timeout(800),
    });
    return response.ok && (await response.json()).service === "talktome";
  } catch {
    return false;
  }
}

// A directory's own size is its inode, so walk it instead.
function sizeOf(target) {
  const info = lstatSync(target);
  if (info.isSymbolicLink()) return 0;
  if (!info.isDirectory()) return info.size;
  return readdirSync(target).reduce(
    (total, entry) => total + sizeOf(path.join(target, entry)),
    0,
  );
}

function stamp() {
  return new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "").replace("T", "-");
}

const directory = dataDir();

if (await running()) {
  console.error(
    `TalkToMe is running on port ${port}. Quit it first — the app rewrites its storage on exit, ` +
      "so clearing it now would be undone.",
  );
  process.exit(1);
}

if (!existsSync(directory)) {
  console.log(`Nothing to reset: ${directory} does not exist yet.`);
  process.exit(0);
}

const present = CLEARED.filter((item) => existsSync(path.join(directory, item)));
if (!present.length) {
  console.log(`Already reset: ${directory} holds no saved settings or setup progress.`);
  process.exit(0);
}

const backup = path.join(path.dirname(directory), `${path.basename(directory)}-backup-${stamp()}`);
mkdirSync(backup, { recursive: true });
for (const item of present) {
  cpSync(path.join(directory, item), path.join(backup, item), { recursive: true });
  rmSync(path.join(directory, item), { recursive: true, force: true });
}

const kept = readdirSync(directory).filter((item) => ["models", "token"].includes(item));
const models = kept.includes("models")
  ? `${Math.round(sizeOf(path.join(directory, "models")) / 1e6)} MB`
  : "none";

console.log(`Cleared ${present.join(", ")}`);
console.log(`Backed up to ${backup}`);
console.log(`Kept ${kept.join(", ") || "nothing"}${models === "none" ? "" : ` (models: ${models})`}`);
console.log("Start the app to run setup again.");
