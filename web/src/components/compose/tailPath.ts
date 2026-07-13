function clamp(value: number, low: number, high: number) {
  return Math.min(high, Math.max(low, value));
}

export function pinnedTailPath(width: number, height: number, targetX: number, targetY: number) {
  const dx = targetX - width / 2;
  const dy = targetY - height / 2;
  const halfBase = Math.max(8, Math.min(16, Math.min(width, height) * 0.12));
  let first: [number, number];
  let second: [number, number];

  if (Math.abs(dx) / Math.max(width, 1) > Math.abs(dy) / Math.max(height, 1)) {
    const edgeX = dx < 0 ? width * 0.06 : width * 0.94;
    const anchorY = clamp(targetY, height * 0.25, height * 0.75);
    first = [edgeX, anchorY - halfBase];
    second = [edgeX, anchorY + halfBase];
  } else {
    const edgeY = dy < 0 ? height * 0.08 : height * 0.92;
    const anchorX = clamp(targetX, width * 0.25, width * 0.75);
    first = [anchorX - halfBase, edgeY];
    second = [anchorX + halfBase, edgeY];
  }

  const firstControl: [number, number] = [
    first[0] + (targetX - first[0]) * 0.38,
    first[1] + (targetY - first[1]) * 0.38,
  ];
  const secondControl: [number, number] = [
    second[0] + (targetX - second[0]) * 0.7,
    second[1] + (targetY - second[1]) * 0.7,
  ];
  return `M ${first[0]} ${first[1]} Q ${firstControl[0]} ${firstControl[1]} ${targetX} ${targetY} Q ${secondControl[0]} ${secondControl[1]} ${second[0]} ${second[1]} Z`;
}
