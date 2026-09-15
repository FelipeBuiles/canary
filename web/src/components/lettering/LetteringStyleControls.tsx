import { useState } from "react";
import { FONT_FILES, type RoleStyle, type FontName } from "@lettering-engine";
import { FieldLabel, SelectField, TextField } from "../ui/Field";
import { useI18n } from "../../i18n";
export function LetteringStyleControls({ value, onChange, idPrefix = "lettering" }: {
  value: RoleStyle;
  onChange: (style: RoleStyle) => void;
  idPrefix?: string;
}) {
  const { t } = useI18n();
  const patch = (key: keyof RoleStyle, newValue: RoleStyle[keyof RoleStyle]) => onChange({ ...value, [key]: newValue });
  const numeric = (key: keyof RoleStyle, label: string, min: number, max: number, step = 1) => <div key={key}>
    <FieldLabel htmlFor={`${idPrefix}-${key}`}>{t(label)}</FieldLabel>
    <NumberField id={`${idPrefix}-${key}`} min={min} max={max} step={step} value={value[key] as number} onChange={n => {
      if (key === "max_font_size")
        onChange({ ...value, max_font_size: n, min_font_size: Math.min(n, value.min_font_size) });
      else if (key === "min_font_size")
        onChange({ ...value, min_font_size: n, max_font_size: Math.max(n, value.max_font_size) });
      else
        patch(key, n);
    }} />
  </div>;
  const color = (key: "color" | "fill" | "stroke" | "text_stroke", label: string) => <div key={key}>
    <FieldLabel htmlFor={`${idPrefix}-${key}`}>{t(label)}</FieldLabel>
    <div className="flex items-center gap-2"><input id={`${idPrefix}-${key}`} type="color" className="lettering-color" value={value[key] === "transparent" ? "#ffffff" : value[key]} onChange={e => patch(key, e.target.value)} />
      {key !== "color" && <label className="lettering-checkbox"><input type="checkbox" checked={value[key] === "transparent"} onChange={e => patch(key, e.target.checked ? "transparent" : "#ffffff")} />{t("None")}</label>}</div>
  </div>;
  return <div className="lettering-style-controls">
    <div><FieldLabel htmlFor={`${idPrefix}-font`}>{t("Typeface")}</FieldLabel><SelectField id={`${idPrefix}-font`} value={value.font} onChange={e => patch("font", e.target.value as FontName)}>
      {Object.keys(FONT_FILES).map(font => <option key={font}>{font}</option>)}
    </SelectField></div>
    <div><FieldLabel htmlFor={`${idPrefix}-weight`}>{t("Weight")}</FieldLabel><SelectField id={`${idPrefix}-weight`} value={value.font_weight} onChange={e => patch("font_weight", Number(e.target.value) as 400 | 700)}><option value={400}>{t("Regular")}</option><option value={700}>{t("Bold")}</option></SelectField></div>
    <div className="lettering-field-pair">{numeric("max_font_size", "Preferred size", 12, 180)}{numeric("min_font_size", "Readable minimum", 12, 100)}</div>
    <div className="lettering-field-pair">{color("color", "Ink")}{color("fill", "Paper / fill")}</div>
    <details><summary>{t("Shape & typography")}</summary><div className="mt-3 space-y-3">
      <div className="lettering-field-pair"><div><FieldLabel htmlFor={`${idPrefix}-shape`}>{t("Shape")}</FieldLabel><SelectField id={`${idPrefix}-shape`} value={value.shape} onChange={e => patch("shape", e.target.value as RoleStyle["shape"])}>{["box", "round", "ellipse", "cloud", "none"].map(shape => <option key={shape} value={shape}>{t(shape)}</option>)}</SelectField></div>
        <div><FieldLabel htmlFor={`${idPrefix}-align`}>{t("Alignment")}</FieldLabel><SelectField id={`${idPrefix}-align`} value={value.align} onChange={e => patch("align", e.target.value as RoleStyle["align"])}>{["left", "center", "right"].map(align => <option key={align} value={align}>{t(align)}</option>)}</SelectField></div></div>
      <div className="lettering-field-pair">{numeric("line_height", "Line spacing", .9, 2, .02)}{numeric("padding", "Padding", 0, 40)}</div>
      <div className="lettering-field-pair">{color("stroke", "Border")}{numeric("stroke_width", "Border width", 0, 12, .2)}</div>
      <div className="lettering-field-pair">{numeric("corner_radius", "Corners", 0, 80)}{numeric("letter_spacing", "Letter spacing", -1, 12, .1)}</div>
      <div className="lettering-field-pair">{color("text_stroke", "Text outline")}{numeric("text_stroke_width", "Text outline width", 0, 12, .2)}</div>
    </div></details>
  </div>;
}
// A transient empty or partial number is not a new style. Keep it editable,
// rather than snapping back on every keystroke; clamp only when committed.
function NumberField({ id, value, min, max, step, onChange }: {
  id: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  return <TextField id={id} type="number" min={min} max={max} step={step} value={draft ?? value} onFocus={() => setDraft(String(value))} onChange={event => {
    const raw = event.currentTarget.value;
    setDraft(raw);
    const number = Number(raw);
    if (raw.trim() && Number.isFinite(number) && number >= min && number <= max)
      onChange(number);
  }} onBlur={() => {
    if (draft?.trim()) {
      const number = Number(draft);
      if (Number.isFinite(number))
        onChange(Math.min(max, Math.max(min, number)));
    } setDraft(null);
  }} onKeyDown={event => {
    if (event.key === "Enter") {
      event.preventDefault();
      event.currentTarget.blur();
    }
  }} />;
}
