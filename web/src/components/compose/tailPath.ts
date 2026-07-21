function clamp(value: number, low: number, high: number) {
  return Math.min(high, Math.max(low, value));
}

export interface SpeechTailGeometry {
  fillPath: string;
  outlinePath: string;
}

export interface ThoughtTailDot {
  cx: number;
  cy: number;
  radius: number;
}

interface TailAttachment {
  anchor: [number, number];
  first: [number, number];
  second: [number, number];
  unit: [number, number];
}

function tailAttachment(width: number, height: number, targetX: number, targetY: number): TailAttachment {
  const dx = targetX - width / 2;
  const dy = targetY - height / 2;
  const distance = Math.max(1, Math.hypot(dx, dy));
  const unit: [number, number] = [dx / distance, dy / distance];
  const halfBase = Math.max(10, Math.min(18, Math.min(width, height) * 0.11));
  let anchor: [number, number];
  let first: [number, number];
  let second: [number, number];

  if (Math.abs(dx) / Math.max(width, 1) > Math.abs(dy) / Math.max(height, 1)) {
    const edgeX = dx < 0 ? width * 0.02 : width * 0.98;
    const projectedY = height / 2 + dy * ((edgeX - width / 2) / (dx || 1));
    const anchorY = clamp(projectedY, height * 0.24, height * 0.76);
    anchor = [edgeX, anchorY];
    first = [edgeX, anchorY - halfBase];
    second = [edgeX, anchorY + halfBase];
  } else {
    const edgeY = dy < 0 ? height * 0.02 : height * 0.98;
    const projectedX = width / 2 + dx * ((edgeY - height / 2) / (dy || 1));
    const anchorX = clamp(projectedX, width * 0.22, width * 0.78);
    anchor = [anchorX, edgeY];
    first = [anchorX - halfBase, edgeY];
    second = [anchorX + halfBase, edgeY];
  }

  return { anchor, first, second, unit };
}

export function speechTailGeometry(
  width: number,
  height: number,
  targetX: number,
  targetY: number,
): SpeechTailGeometry {
  const { first, second, unit } = tailAttachment(width, height, targetX, targetY);
  const distance = Math.max(1, Math.hypot(targetX - first[0], targetY - first[1]));
  const innerFirst: [number, number] = [first[0] - unit[0] * 7, first[1] - unit[1] * 7];
  const innerSecond: [number, number] = [second[0] - unit[0] * 7, second[1] - unit[1] * 7];

  const firstControl: [number, number] = [
    first[0] + unit[0] * distance * 0.42,
    first[1] + unit[1] * distance * 0.42,
  ];
  const secondControl: [number, number] = [
    second[0] + (targetX - second[0]) * 0.72,
    second[1] + (targetY - second[1]) * 0.72,
  ];
  const curve = `M ${first[0]} ${first[1]} C ${firstControl[0]} ${firstControl[1]} ${targetX} ${targetY} ${targetX} ${targetY} C ${targetX} ${targetY} ${secondControl[0]} ${secondControl[1]} ${second[0]} ${second[1]}`;
  return {
    fillPath: `M ${innerFirst[0]} ${innerFirst[1]} L ${first[0]} ${first[1]} C ${firstControl[0]} ${firstControl[1]} ${targetX} ${targetY} ${targetX} ${targetY} C ${targetX} ${targetY} ${secondControl[0]} ${secondControl[1]} ${second[0]} ${second[1]} L ${innerSecond[0]} ${innerSecond[1]} Z`,
    outlinePath: curve,
  };
}

export function thoughtTailDots(
  width: number,
  height: number,
  targetX: number,
  targetY: number,
): ThoughtTailDot[] {
  const { anchor, unit } = tailAttachment(width, height, targetX, targetY);
  const start: [number, number] = [anchor[0] + unit[0] * 5, anchor[1] + unit[1] * 5];
  const end: [number, number] = [targetX - unit[0] * 3, targetY - unit[1] * 3];
  const stops = [0, 0.34, 0.68, 1];
  const radii = [11, 8, 5.5, 3.5];
  return stops.map((stop, index) => ({
    cx: start[0] + (end[0] - start[0]) * stop,
    cy: start[1] + (end[1] - start[1]) * stop,
    radius: radii[index],
  }));
}
