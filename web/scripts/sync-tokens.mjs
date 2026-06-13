// Copy the canonical theme tokens from the Python package into the web tree so
// the live canvas and the PNG/PDF renderer share one source of truth.
// Wired into `dev` and `build`; a vitest parity test guards against drift.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(
  here,
  "../../novel_to_comic/src/novel_to_comic/assembly/theme_tokens.json",
);
const dest = resolve(here, "../src/generated/theme_tokens.json");

mkdirSync(dirname(dest), { recursive: true });
copyFileSync(src, dest);
console.log(`synced theme tokens -> ${dest}`);
