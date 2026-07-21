import { createHash } from "node:crypto";
import { mkdtemp, readFile, readdir, rm, stat } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

import {
  buildBrandAssets,
  DEFAULT_OUTPUT_DIR,
  PUBLIC_ROOT,
  publishApprovedBrandAssets,
  RUNTIME_ASSET_MAP,
} from "./build.ts";
import { PALETTE } from "./geometry.ts";

const EXPECTED_FILES = [
  "scenewright-symbol-primary.svg",
  "scenewright-symbol-reversed.svg",
  "scenewright-symbol-black.svg",
  "scenewright-symbol-white.svg",
  "scenewright-symbol-red.svg",
  "scenewright-symbol-micro.svg",
  "scenewright-app-icon.svg",
  "scenewright-app-icon-1024.png",
  "scenewright-app-icon-512.png",
  "scenewright-app-icon-256.png",
  "scenewright-app-icon-128.png",
  "scenewright-app-icon-64.png",
  "favicon.svg",
  "favicon-16.png",
  "favicon-32.png",
  "favicon-48.png",
  "favicon.ico",
  "scenewright-wordmark.svg",
  "scenewright-lockup-horizontal.svg",
  "scenewright-lockup-horizontal-reversed.svg",
  "scenewright-lockup-stacked.svg",
  "scenewright-symbol-geometry-debug.svg",
  "scenewright-contact-sheet.png",
  "README.md",
];

function invariant(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

async function fileMap(root: string): Promise<Map<string, Buffer>> {
  const result = new Map<string, Buffer>();
  async function visit(directory: string): Promise<void> {
    for (const entry of (await readdir(directory)).sort()) {
      const absolute = path.join(directory, entry);
      const metadata = await stat(absolute);
      if (metadata.isDirectory()) await visit(absolute);
      else result.set(path.relative(root, absolute), await readFile(absolute));
    }
  }
  await visit(root);
  return result;
}

async function validateSvg(filename: string, data: Buffer): Promise<void> {
  const svg = data.toString("utf8");
  invariant(/<svg\b[^>]*\bviewBox="[^"]+"/.test(svg), `${filename} lacks a viewBox`);
  invariant(!/<image\b/i.test(svg), `${filename} embeds a raster image`);
  invariant(!/<(?:linearGradient|radialGradient)\b/i.test(svg), `${filename} contains a gradient`);
  invariant(!/\b(?:href|src)="(?:https?:)?\/\//i.test(svg), `${filename} contains an external URL`);
  invariant(!/\burl\(/i.test(svg), `${filename} contains an external or paint-server URL`);
  invariant(!/<metadata\b/i.test(svg), `${filename} contains editor metadata`);
  invariant(/<title\b/.test(svg) && /<desc\b/.test(svg), `${filename} lacks title or description metadata`);
  if (/data-wordmark-mode="outlined"/.test(svg)) {
    invariant(!/<text\b|font-family=/i.test(svg), `${filename} claims to be outlined but still contains font-dependent text`);
  }
}

async function validatePngDimensions(root: string): Promise<void> {
  for (const size of [1024, 512, 256, 128, 64]) {
    const metadata = await sharp(path.join(root, `scenewright-app-icon-${size}.png`)).metadata();
    invariant(metadata.width === size && metadata.height === size, `App icon ${size} has incorrect dimensions`);
  }
  for (const size of [16, 32, 48]) {
    const metadata = await sharp(path.join(root, `favicon-${size}.png`)).metadata();
    invariant(metadata.width === size && metadata.height === size, `Favicon ${size} has incorrect dimensions`);
  }
}

async function validateIco(root: string): Promise<void> {
  const ico = await readFile(path.join(root, "favicon.ico"));
  invariant(ico.readUInt16LE(2) === 1, "favicon.ico is not an icon resource");
  invariant(ico.readUInt16LE(4) === 3, "favicon.ico must contain exactly 16, 32, and 48 pixel images");
  const sizes = [0, 1, 2].map((index) => ico.readUInt8(6 + index * 16));
  invariant(sizes.join(",") === "16,32,48", `favicon.ico has incorrect sizes: ${sizes.join(",")}`);
}

async function validatePrimaryPalette(root: string): Promise<void> {
  const svg = await readFile(path.join(root, "scenewright-symbol-primary.svg"), "utf8");
  const colors = new Set((svg.match(/#[0-9a-f]{6}/gi) ?? []).map((color) => color.toLowerCase()));
  const allowed = new Set([PALETTE.heroRed, PALETTE.inkBlack, PALETTE.pulpPaper]);
  for (const color of colors) invariant(allowed.has(color as never), `Primary symbol contains non-canonical color ${color}`);
  invariant((svg.match(/<circle\b/g) ?? []).length >= 90, "Primary symbol is missing its vector Ben-Day layer");
  invariant(svg.includes(PALETTE.pulpPaper), "Primary symbol must use pulp paper for its channel cutouts");
  invariant(!new RegExp(`stroke="${PALETTE.heroRed}"`, "i").test(svg), "Primary symbol must not add a red border");

  const micro = await readFile(path.join(root, "scenewright-symbol-micro.svg"), "utf8");
  invariant(!/<circle\b/.test(micro), "Micro symbol must omit Ben-Day dots for reduction");
}

async function validatePublishedAssets(): Promise<void> {
  for (const [source, destination] of Object.entries(RUNTIME_ASSET_MAP)) {
    const [generated, published] = await Promise.all([
      readFile(path.join(DEFAULT_OUTPUT_DIR, source)),
      readFile(path.join(PUBLIC_ROOT, destination)),
    ]);
    invariant(
      generated.equals(published),
      `Published runtime asset ${destination} does not match generated source ${source}`,
    );
  }
}

async function validateDeterminism(): Promise<void> {
  const first = await mkdtemp(path.join(os.tmpdir(), "scenewright-brand-a-"));
  const second = await mkdtemp(path.join(os.tmpdir(), "scenewright-brand-b-"));
  try {
    await buildBrandAssets(first);
    await buildBrandAssets(second);
    const [a, b] = await Promise.all([fileMap(first), fileMap(second)]);
    invariant(a.size === b.size, "Consecutive builds produced different file counts");
    for (const [filename, content] of a) {
      const other = b.get(filename);
      invariant(other, `Second build is missing ${filename}`);
      const hashA = createHash("sha256").update(content).digest("hex");
      const hashB = createHash("sha256").update(other).digest("hex");
      invariant(hashA === hashB, `${filename} changed between consecutive builds`);
    }
  } finally {
    await Promise.all([rm(first, { recursive: true, force: true }), rm(second, { recursive: true, force: true })]);
  }
}

export async function validateBrandAssets(root = DEFAULT_OUTPUT_DIR): Promise<void> {
  const files = await fileMap(root);
  for (const filename of EXPECTED_FILES) invariant(files.has(filename), `Missing expected output ${filename}`);
  for (const [filename, data] of files) if (filename.endsWith(".svg")) await validateSvg(filename, data);
  await validatePngDimensions(root);
  await validateIco(root);
  await validatePrimaryPalette(root);
  await validateDeterminism();
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : "";
if (invokedPath === fileURLToPath(import.meta.url)) {
  await publishApprovedBrandAssets();
  await validateBrandAssets();
  await validatePublishedAssets();
  console.log(
    `Validated ${EXPECTED_FILES.length} Scenewright brand outputs, runtime icons, and deterministic rebuilds.`,
  );
}
