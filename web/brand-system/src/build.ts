import { copyFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

import {
  PALETTE,
  geometryDebugSvg,
  svgDocument,
  symbolElements,
  symbolSvg,
  wordmarkText,
  type SymbolVariant,
} from "./geometry.ts";

const SOURCE_DIR = path.dirname(fileURLToPath(import.meta.url));
export const DEFAULT_OUTPUT_DIR = path.resolve(SOURCE_DIR, "../../public/brand/scenewright-panel-frame");
export const PUBLIC_ROOT = path.resolve(SOURCE_DIR, "../../public");

export const RUNTIME_ASSET_MAP = {
  "favicon.svg": "favicon.svg",
  "favicon-16.png": "favicon-16.png",
  "favicon-32.png": "favicon-32.png",
  "favicon-48.png": "favicon-48.png",
  "favicon.ico": "favicon.ico",
  "scenewright-app-icon-256.png": "apple-touch-icon.png",
} as const;

const SYMBOL_FILES: Record<string, SymbolVariant> = {
  "scenewright-symbol-primary.svg": "primary",
  "scenewright-symbol-reversed.svg": "reversed",
  "scenewright-symbol-black.svg": "black",
  "scenewright-symbol-white.svg": "white",
  "scenewright-symbol-red.svg": "red",
  "scenewright-symbol-micro.svg": "micro",
};

function groupSymbol(variant: SymbolVariant, x: number, y: number, scale: number): string {
  return `    <g transform="translate(${x} ${y}) scale(${scale})">\n${symbolElements(variant)}\n    </g>`;
}

export function appIconSvg(): string {
  return svgDocument(
    "Scenewright app icon",
    "The Scenewright Panel Frame S centered in a pulp-paper rounded-square app tile.",
    "0 0 100 100",
    [
      `    <rect x="3" y="3" width="94" height="94" rx="18" fill="${PALETTE.pulpPaper}" stroke="${PALETTE.inkBlack}" stroke-width="2" />`,
      groupSymbol("primary", 7, 7, 0.86),
    ].join("\n"),
  );
}

export function faviconSvg(): string {
  return svgDocument(
    "Scenewright favicon",
    "A simplified red S-in-panel mark optimized for 16 to 48 pixels.",
    "0 0 100 100",
    symbolElements("micro"),
  );
}

export function wordmarkSvg(color = PALETTE.inkBlack): string {
  return svgDocument(
    "Scenewright wordmark",
    "The uppercase Scenewright live-text wordmark. It remains provisional until the licensed Anybody font is supplied for outlining.",
    "0 0 450 88",
    wordmarkText(color),
    'data-production-status="live-text-provisional"',
  );
}

export function horizontalLockupSvg(reversed = false): string {
  const variant: SymbolVariant = reversed ? "reversed" : "primary";
  const wordColor = reversed ? PALETTE.pulpPaper : PALETTE.inkBlack;
  return svgDocument(
    reversed ? "Scenewright horizontal lockup, reversed" : "Scenewright horizontal lockup",
    reversed
      ? "The Scenewright Panel Frame S and uppercase wordmark for ink-black backgrounds."
      : "The Scenewright Panel Frame S and uppercase wordmark arranged horizontally.",
    "0 0 580 110",
    [
      groupSymbol(variant, 7, 11, 0.86),
      wordmarkText(wordColor, 112, 77, 450),
    ].join("\n"),
    'data-production-status="live-text-provisional"',
  );
}

export function stackedLockupSvg(): string {
  return svgDocument(
    "Scenewright stacked lockup",
    "The Scenewright Panel Frame S above the uppercase Scenewright wordmark.",
    "0 0 500 225",
    [
      groupSymbol("primary", 195, 2, 1.1),
      wordmarkText(PALETTE.inkBlack, 25, 202, 450),
    ].join("\n"),
    'data-production-status="live-text-provisional"',
  );
}

function contactSheetSvg(): string {
  const contactWordmark = (color: string, x: number, baseline: number, length: number) =>
    `<text x="${x}" y="${baseline}" fill="${color}" font-family="Arial Black, sans-serif" font-size="72" font-weight="900" letter-spacing="-2" textLength="${length}" lengthAdjust="spacingAndGlyphs">SCENEWRIGHT</text>`;
  const swatch = (x: number, color: string, label: string) => `
    <rect x="${x}" y="1020" width="128" height="64" fill="${color}" stroke="${PALETTE.inkBlack}" stroke-width="2" />
    <text x="${x}" y="1112" class="swatch-label">${label}</text>
    <text x="${x}" y="1138" class="swatch-code">${color.toUpperCase()}</text>`;
  const variantCard = (variant: SymbolVariant, x: number, label: string, background: string = PALETTE.pulpPaper) => `
    <rect x="${x}" y="200" width="250" height="250" fill="${background}" stroke="${PALETTE.inkBlack}" stroke-width="2" />
    <g transform="translate(${x + 40} 240) scale(1.7)">${symbolElements(variant)}</g>
    <text x="${x}" y="482" class="meta">${label}</text>`;

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1800 1200">
  <style>
    .display { font: 900 84px 'Arial Black', sans-serif; letter-spacing: -3px; fill: ${PALETTE.inkBlack}; }
    .meta { font: 700 22px Arial, sans-serif; letter-spacing: 3px; fill: ${PALETTE.inkBlack}; }
    .code { font: 18px monospace; fill: ${PALETTE.inkBlack}; }
    .small { font: 700 18px Arial, sans-serif; letter-spacing: 2px; fill: ${PALETTE.inkBlack}; }
    .swatch-label { font: 700 14px Arial, sans-serif; letter-spacing: 1.2px; fill: ${PALETTE.inkBlack}; }
    .swatch-code { font: 15px monospace; fill: ${PALETTE.inkBlack}; }
  </style>
  <rect width="1800" height="1200" fill="${PALETTE.pulpPaper}" />
  <text x="72" y="104" class="display">SCENEWRIGHT</text>
  <text x="76" y="150" class="meta">PANEL FRAME S / IDENTITY CONTACT SHEET</text>
  ${variantCard("primary", 72, "PRIMARY")}
  ${variantCard("reversed", 352, "REVERSED", PALETTE.inkBlack)}
  ${variantCard("black", 632, "ONE-COLOR BLACK")}
  ${variantCard("white", 912, "ONE-COLOR WHITE", PALETTE.inkBlack)}
  ${variantCard("red", 1192, "ONE-COLOR RED")}
  ${variantCard("micro", 1472, "MICRO")}
  <rect x="72" y="550" width="980" height="190" fill="${PALETTE.pulpPaper}" stroke="${PALETTE.inkBlack}" stroke-width="2" />
  ${groupSymbol("primary", 95, 580, 1.25)}
  ${contactWordmark(PALETTE.inkBlack, 255, 684, 720)}
  <text x="72" y="778" class="meta">HORIZONTAL LOCKUP / LIVE-TEXT WORDMARK</text>
  <rect x="1265" y="550" width="390" height="390" rx="70" fill="${PALETTE.pulpPaper}" stroke="${PALETTE.inkBlack}" stroke-width="4" />
  ${groupSymbol("primary", 1288, 573, 3.44)}
  <text x="1265" y="978" class="meta">APP ICON</text>
  <text x="72" y="878" class="meta">FAVICON / ACTUAL SIZE</text>
  ${[16, 24, 32, 48, 64].map((size, index) => {
    const x = 72 + index * 132;
    const scale = size / 100;
    return `<g transform="translate(${x} 910) scale(${scale})">${symbolElements("micro")}</g><text x="${x + size + 12}" y="${930 + size / 2}" class="small">${size}</text>`;
  }).join("\n")}
  ${swatch(72, PALETTE.heroRed, "HERO RED")}
  ${swatch(230, PALETTE.inkBlack, "INK BLACK")}
  ${swatch(388, PALETTE.pulpPaper, "PULP PAPER")}
  ${swatch(546, PALETTE.bristolWhite, "BRISTOL")}
  ${swatch(704, PALETTE.archiveSage, "ARCHIVE SAGE")}
  ${swatch(862, PALETTE.narratorGold, "NARRATOR GOLD")}
  <text x="1130" y="1110" class="small">VECTOR BEN-DAY / 100-UNIT MASTER</text>
</svg>`;
}

function icoBuffer(images: Array<{ size: number; data: Buffer }>): Buffer {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(images.length, 4);

  const entries: Buffer[] = [];
  let offset = 6 + images.length * 16;
  for (const image of images) {
    const entry = Buffer.alloc(16);
    entry.writeUInt8(image.size === 256 ? 0 : image.size, 0);
    entry.writeUInt8(image.size === 256 ? 0 : image.size, 1);
    entry.writeUInt8(0, 2);
    entry.writeUInt8(0, 3);
    entry.writeUInt16LE(1, 4);
    entry.writeUInt16LE(32, 6);
    entry.writeUInt32LE(image.data.length, 8);
    entry.writeUInt32LE(offset, 12);
    entries.push(entry);
    offset += image.data.length;
  }
  return Buffer.concat([header, ...entries, ...images.map((image) => image.data)]);
}

async function pngFromSvg(svg: string, size: number): Promise<Buffer> {
  return sharp(Buffer.from(svg))
    .resize(size, size, { fit: "fill", kernel: sharp.kernel.lanczos3 })
    .png({ compressionLevel: 9, adaptiveFiltering: false, palette: false })
    .toBuffer();
}

const OUTPUT_README = `# Scenewright — Panel Frame S assets

Generated deterministically from \`web/brand-system/src/geometry.ts\`.

The canonical symbol uses the current product palette: hero red \`${PALETTE.heroRed}\`, ink black \`${PALETTE.inkBlack}\`, pulp paper \`${PALETTE.pulpPaper}\`, Bristol white \`${PALETTE.bristolWhite}\`, and archive sage \`${PALETTE.archiveSage}\` for demonstrations.

The full-color primary and reversed marks use a deterministic vector Ben-Day layer made from explicit circles—no raster texture, masks, gradients, embedded images, or external references. The micro and one-color masters omit texture for reduction and reproduction. One-color channel cutouts use an even-odd compound path so the negative space remains transparent.

The wordmark and lockups are intentionally marked \`live-text-provisional\`. Anybody is referenced first because it is the application's title family, but no locally licensed font file was available during generation. The specimen loads the same hosted Anybody source as the current app. Do not treat the wordmark as print-ready until Anybody is supplied and converted to outlines. The symbol assets are production-ready and approved for product use.

When an SVG is decorative beside visible text, consumers should add \`aria-hidden="true"\` and remove it from the focus order. The shipped files otherwise contain \`role="img"\`, \`<title>\`, and \`<desc>\` for direct use.
`;

export async function buildBrandAssets(outputDir = DEFAULT_OUTPUT_DIR): Promise<void> {
  await mkdir(outputDir, { recursive: true });

  for (const [filename, variant] of Object.entries(SYMBOL_FILES)) {
    await writeFile(path.join(outputDir, filename), symbolSvg(variant), "utf8");
  }

  const svgs: Record<string, string> = {
    "scenewright-app-icon.svg": appIconSvg(),
    "favicon.svg": faviconSvg(),
    "scenewright-wordmark.svg": wordmarkSvg(),
    "scenewright-lockup-horizontal.svg": horizontalLockupSvg(),
    "scenewright-lockup-horizontal-reversed.svg": horizontalLockupSvg(true),
    "scenewright-lockup-stacked.svg": stackedLockupSvg(),
    "scenewright-symbol-geometry-debug.svg": geometryDebugSvg(),
  };

  for (const [filename, svg] of Object.entries(svgs)) {
    await writeFile(path.join(outputDir, filename), svg, "utf8");
  }

  for (const size of [1024, 512, 256, 128, 64]) {
    const png = await pngFromSvg(svgs["scenewright-app-icon.svg"], size);
    await writeFile(path.join(outputDir, `scenewright-app-icon-${size}.png`), png);
  }

  const faviconImages: Array<{ size: number; data: Buffer }> = [];
  for (const size of [16, 32, 48]) {
    const png = await pngFromSvg(svgs["favicon.svg"], size);
    faviconImages.push({ size, data: png });
    await writeFile(path.join(outputDir, `favicon-${size}.png`), png);
  }
  await writeFile(path.join(outputDir, "favicon.ico"), icoBuffer(faviconImages));

  const contactSheet = await sharp(Buffer.from(contactSheetSvg()))
    .resize(1800, 1200, { fit: "fill" })
    .png({ compressionLevel: 9, adaptiveFiltering: false, palette: false })
    .toBuffer();
  await writeFile(path.join(outputDir, "scenewright-contact-sheet.png"), contactSheet);
  await writeFile(path.join(outputDir, "README.md"), OUTPUT_README, "utf8");
}

export async function publishApprovedBrandAssets(): Promise<void> {
  await buildBrandAssets(DEFAULT_OUTPUT_DIR);
  await mkdir(PUBLIC_ROOT, { recursive: true });
  for (const [source, destination] of Object.entries(RUNTIME_ASSET_MAP)) {
    await copyFile(path.join(DEFAULT_OUTPUT_DIR, source), path.join(PUBLIC_ROOT, destination));
  }
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : "";
if (invokedPath === fileURLToPath(import.meta.url)) {
  await publishApprovedBrandAssets();
  console.log(`Built Scenewright brand assets in ${DEFAULT_OUTPUT_DIR} and published runtime icons.`);
}
