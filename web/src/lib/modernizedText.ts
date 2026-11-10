/** A modernized passage as manuscript text: one paragraph per blank-line block, ready to upload or paste. */
export function modernizedText(paragraphs: string[]): string {
  return `${paragraphs.map((paragraph) => paragraph.trim()).join("\n\n")}\n`;
}

/** "the-monkeys-paw-gemini-4-carbon.txt" from a project title and model. */
export function modernizedFilename(title: string, model: string): string {
  const slug = (value: string) => value.normalize("NFKD").toLowerCase()
    .replace(/[’']/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return `${[slug(title), slug(model)].filter(Boolean).join("-") || "modernized"}.txt`;
}
