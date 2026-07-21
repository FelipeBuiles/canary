export const PALETTE = {
  heroRed: "#b51822",
  inkBlack: "#1b1c15",
  pulpPaper: "#fcfaed",
  bristolWhite: "#ffffff",
  archiveSage: "#4a7c59",
  narratorGold: "#fae361",
  surfaceContainer: "#f0eee1",
} as const;

export const SYMBOL_GRID = {
  viewBox: "0 0 100 100",
  frame: { min: 17.5, max: 82.5, innerMin: 20.5, innerMax: 79.5, gapMin: 47, gapMax: 53 },
  field: { min: 24, max: 76 },
  ticks: {
    top: { x: 49.5, y: 6.5, width: 1, height: 8 },
    right: { x: 85.5, y: 49.5, width: 8, height: 1 },
    bottom: { x: 49.5, y: 85.5, width: 1, height: 8 },
    left: { x: 6.5, y: 49.5, width: 8, height: 1 },
  },
  channels: {
    upper: [[39, 36.5], [76, 36.5], [76, 44], [39, 41]] as const,
    lower: [[24, 55], [62, 59], [62, 64.5], [24, 64.5]] as const,
  },
} as const;

export const MICRO_GRID = {
  frame: { min: 12, max: 88, innerMin: 18, innerMax: 82 },
  field: { min: 22, max: 78 },
  channels: {
    upper: [[38, 34], [78, 34], [78, 46], [38, 41]] as const,
    lower: [[22, 53], [62, 59], [62, 67], [22, 67]] as const,
  },
} as const;

export type SymbolVariant = "primary" | "reversed" | "black" | "white" | "red" | "micro";

type Point = readonly [number, number];

function polygonPath(points: readonly Point[]): string {
  return `${points.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x} ${y}`).join(" ")} Z`;
}

function frameCorners(color: string): string {
  return [
    "M17.5 47 H20.5 V20.5 H47 V17.5 H17.5 Z",
    "M53 17.5 H82.5 V47 H79.5 V20.5 H53 Z",
    "M17.5 53 H20.5 V79.5 H47 V82.5 H17.5 Z",
    "M79.5 53 H82.5 V82.5 H53 V79.5 H79.5 Z",
  ].map((d) => `    <path d="${d}" fill="${color}" />`).join("\n");
}

function registrationTicks(color: string): string {
  return Object.values(SYMBOL_GRID.ticks)
    .map(({ x, y, width, height }) => `    <rect x="${x}" y="${y}" width="${width}" height="${height}" fill="${color}" />`)
    .join("\n");
}

function fieldWithTransparentChannels(color: string, micro = false): string {
  const grid = micro ? MICRO_GRID : SYMBOL_GRID;
  const { min, max } = grid.field;
  const field = `M${min} ${min} H${max} V${max} H${min} Z`;
  const channels = `${polygonPath(grid.channels.upper)} ${polygonPath(grid.channels.lower)}`;
  return `    <path d="${field} ${channels}" fill="${color}" fill-rule="evenodd" clip-rule="evenodd" />`;
}

function bendayDots(): string {
  const dots: string[] = [];

  for (let row = 0; row < 5; row += 1) {
    for (let column = 0; column < 6; column += 1) {
      const x = 26.5 + column * 3 + (row % 2 === 1 ? 1.5 : 0);
      const y = 26.5 + row * 3;
      const radius = Math.max(0.24, 0.78 - (column + row) * 0.055).toFixed(2);
      dots.push(`    <circle cx="${x}" cy="${y}" r="${radius}" fill="${PALETTE.pulpPaper}" />`);
    }
  }

  for (let row = 0; row < 5; row += 1) {
    for (let column = 0; column < 6; column += 1) {
      const x = 35 + column * 3 + (row % 2 === 1 ? 1.5 : 0);
      const y = 27.5 + row * 3;
      const radius = Math.min(0.95, 0.28 + (column + row) * 0.07).toFixed(2);
      dots.push(`    <circle cx="${x}" cy="${y}" r="${radius}" fill="${PALETTE.inkBlack}" />`);
    }
  }

  for (let row = 0; row < 6; row += 1) {
    for (let column = 0; column < 7; column += 1) {
      const x = 55 + column * 3 + (row % 2 === 1 ? 1.5 : 0);
      const y = 58 + row * 3;
      const radius = Math.min(1.18, 0.26 + (column + row) * 0.075).toFixed(2);
      dots.push(`    <circle cx="${x}" cy="${y}" r="${radius}" fill="${PALETTE.inkBlack}" />`);
    }
  }

  return dots.join("\n");
}

function fieldWithSolidChannels(fieldColor: string, channelColor: string, micro = false, textured = false): string {
  const grid = micro ? MICRO_GRID : SYMBOL_GRID;
  const { min, max } = grid.field;
  return [
    `    <rect x="${min}" y="${min}" width="${max - min}" height="${max - min}" fill="${fieldColor}" stroke="none" shape-rendering="crispEdges" />`,
    textured ? bendayDots() : "",
    `    <path d="${polygonPath(grid.channels.upper)} ${polygonPath(grid.channels.lower)}" fill="${channelColor}" />`,
  ].filter(Boolean).join("\n");
}

function microFrame(color: string): string {
  const { min, max, innerMin, innerMax } = MICRO_GRID.frame;
  const outer = `M${min} ${min} H${max} V${max} H${min} Z`;
  const inner = `M${innerMin} ${innerMin} V${innerMax} H${innerMax} V${innerMin} Z`;
  return `    <path d="${outer} ${inner}" fill="${color}" fill-rule="evenodd" clip-rule="evenodd" />`;
}

export function symbolElements(variant: SymbolVariant): string {
  if (variant === "micro") {
    return [
      microFrame(PALETTE.inkBlack),
      fieldWithSolidChannels(PALETTE.heroRed, PALETTE.pulpPaper, true),
    ].join("\n");
  }

  const oneColor = variant === "black" || variant === "white" || variant === "red";
  const frameColor = variant === "reversed" ? PALETTE.pulpPaper
    : variant === "white" ? PALETTE.bristolWhite
      : variant === "red" ? PALETTE.heroRed
        : PALETTE.inkBlack;

  const fieldColor = variant === "reversed" || variant === "primary" ? PALETTE.heroRed : frameColor;
  const channelColor = PALETTE.pulpPaper;

  return [
    frameCorners(frameColor),
    registrationTicks(frameColor),
    oneColor ? fieldWithTransparentChannels(fieldColor) : fieldWithSolidChannels(fieldColor, channelColor, false, true),
  ].join("\n");
}

export function svgDocument(
  title: string,
  description: string,
  viewBox: string,
  content: string,
  attributes = "",
): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}" role="img" aria-labelledby="title desc"${attributes ? ` ${attributes}` : ""}>
  <title id="title">${title}</title>
  <desc id="desc">${description}</desc>
${content}
</svg>\n`;
}

export function symbolSvg(variant: SymbolVariant): string {
  const labels: Record<SymbolVariant, [string, string]> = {
    primary: ["Scenewright symbol", "A red editorial panel forms an abstract S inside black registration brackets."],
    reversed: ["Scenewright reversed symbol", "A red editorial panel forms an abstract S inside light registration brackets for dark backgrounds."],
    black: ["Scenewright black symbol", "A one-color black editorial panel symbol with a transparent S cut through it."],
    white: ["Scenewright white symbol", "A one-color white editorial panel symbol with a transparent S cut through it."],
    red: ["Scenewright red symbol", "A one-color red editorial panel symbol with a transparent S cut through it."],
    micro: ["Scenewright micro symbol", "A simplified S-in-panel symbol optimized for favicon sizes."],
  };
  const [title, description] = labels[variant];
  return svgDocument(title, description, SYMBOL_GRID.viewBox, symbolElements(variant));
}

export function wordmarkText(color: string, x = 0, baseline = 70, length = 450): string {
  return `    <text x="${x}" y="${baseline}" fill="${color}" font-family="Anybody, sans-serif" font-size="72" font-weight="900" letter-spacing="-2.2" textLength="${length}" lengthAdjust="spacingAndGlyphs" data-wordmark-mode="live-text-provisional">SCENEWRIGHT</text>`;
}

export function geometryDebugSvg(): string {
  const lines: string[] = [];
  for (let value = 0; value <= 100; value += 5) {
    const major = value % 10 === 0;
    lines.push(`    <path d="M${value} 0 V100 M0 ${value} H100" stroke="${major ? PALETTE.inkBlack : PALETTE.archiveSage}" stroke-width="${major ? 0.35 : 0.18}" opacity="${major ? 0.28 : 0.16}" />`);
  }
  const anchors = [
    ...SYMBOL_GRID.channels.upper,
    ...SYMBOL_GRID.channels.lower,
  ].map(([x, y]) => `    <circle cx="${x}" cy="${y}" r="1.25" fill="${PALETTE.narratorGold}" stroke="${PALETTE.inkBlack}" stroke-width="0.5" />`);

  return svgDocument(
    "Scenewright symbol geometry",
    "The 100-unit construction grid, panel geometry, channel anchors, and registration marks used by the Scenewright symbol.",
    SYMBOL_GRID.viewBox,
    [
      `    <rect width="100" height="100" fill="${PALETTE.pulpPaper}" />`,
      ...lines,
      symbolElements("primary"),
      ...anchors,
      `    <rect x="24" y="24" width="52" height="52" fill="none" stroke="${PALETTE.narratorGold}" stroke-width="0.6" stroke-dasharray="2 2" />`,
    ].join("\n"),
  );
}
