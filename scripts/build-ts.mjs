// Compile the TypeScript in desktop/src to CommonJS in desktop/build.
// The repository is "type": "module", so the build folder says it is CommonJS.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
execFileSync(path.join(root, "node_modules", ".bin", "tsc"), ["-p", path.join(root, "tsconfig.json")], { stdio: "inherit" });
fs.writeFileSync(path.join(root, "desktop", "build", "package.json"), '{ "type": "commonjs" }\n');
