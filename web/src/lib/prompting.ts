import type { ImagePrompt, PromptSubject } from "../types/api";

const LABELS = {
  composition: "Composition",
  setting: "Setting",
  lighting: "Lighting",
  mood: "Mood",
  keyProps: "Key props",
  expression: "expression",
  position: "position",
};

function clean(value: string | null | undefined): string {
  return (value ?? "").replace(/\n/g, " ").split(/\s+/).filter(Boolean).join(" ");
}

function renderSubject(subject: PromptSubject): string {
  const details = [
    subject.name,
    subject.identity,
    subject.action,
    subject.expression ? `${LABELS.expression}: ${subject.expression}` : "",
    subject.position ? `${LABELS.position}: ${subject.position}` : "",
  ];
  return details.map((part) => clean(part)).filter(Boolean).join(", ");
}

export function renderPanelPromptBody(prompt: Pick<ImagePrompt, "subjects" | "composition" | "setting" | "lighting" | "mood" | "props" | "constraints">): string {
  const sentences: string[] = [];
  const subjects = prompt.subjects ?? [];

  if (subjects.length > 0) {
    const rendered = subjects.map((subject) => renderSubject(subject)).filter(Boolean);
    if (rendered.length > 0) sentences.push(rendered.join("; "));
  }

  const composition = clean(prompt.composition);
  if (composition) sentences.push(`${LABELS.composition}: ${composition}`);

  const setting = clean(prompt.setting);
  if (setting) sentences.push(`${LABELS.setting}: ${setting}`);

  const lighting = clean(prompt.lighting);
  if (lighting) sentences.push(`${LABELS.lighting}: ${lighting}`);

  const mood = clean(prompt.mood);
  if (mood) sentences.push(`${LABELS.mood}: ${mood}`);

  const props = (prompt.props ?? []).map((prop) => clean(prop)).filter(Boolean);
  if (props.length > 0) sentences.push(`${LABELS.keyProps}: ${props.join("; ")}`);

  const constraints = clean(prompt.constraints);
  if (constraints) sentences.push(constraints);

  const body = sentences.map((sentence) => sentence.replace(/[ .]+$/, "")).filter(Boolean).join(". ").trim();
  return body ? `${body}.` : "";
}
