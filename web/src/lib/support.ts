export interface SupportDiagnostics {
  releaseSha?: string | null;
  projectId?: string | null;
  stationOrStage?: string | null;
  requestId?: string | null;
  errorCategory?: string | null;
}

function safeDiagnostic(value: string | null | undefined): string | null {
  if (!value) return null;
  const candidate = value.trim();
  if (!/^[a-zA-Z0-9._:/-]+$/.test(candidate)) return null;
  return candidate.slice(0, 160);
}

export function supportMailto(
  email: string,
  diagnostics: SupportDiagnostics = {},
): string {
  const lines = [
    ["Release", diagnostics.releaseSha],
    ["Project", diagnostics.projectId],
    ["Station/stage", diagnostics.stationOrStage],
    ["Request", diagnostics.requestId],
    ["Category", diagnostics.errorCategory],
  ]
    .map(([label, value]) => {
      const safe = safeDiagnostic(value);
      return safe ? `${label}: ${safe}` : null;
    })
    .filter((line): line is string => line !== null);

  const query = new URLSearchParams({
    subject: "Scenewright support request",
    body: [
      "Tell us what happened. Do not include manuscript text, prompts, passwords, or API keys.",
      "",
      ...lines,
    ].join("\n"),
  });
  return `mailto:${email}?${query.toString()}`;
}
