/// <reference types="node" />
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import generated from "../generated/theme_tokens.json";

describe("theme tokens parity", () => {
  it("the synced web copy matches the canonical backend tokens", () => {
    // vitest runs with cwd = web/, so the backend file is one level up.
    const canonicalPath = resolve(
      process.cwd(),
      "../novel_to_comic/src/novel_to_comic/assembly/theme_tokens.json",
    );
    const canonical = JSON.parse(readFileSync(canonicalPath, "utf-8"));
    expect(generated).toEqual(canonical);
  });

  it("every font pair defines both font vars", () => {
    const pairs = (generated as { font_pairs: Record<string, Record<string, string>> }).font_pairs;
    for (const [id, vars] of Object.entries(pairs)) {
      expect(vars["--letter-font"], `${id} --letter-font`).toBeTruthy();
      expect(vars["--display-font"], `${id} --display-font`).toBeTruthy();
    }
  });
});
