import { useId, useState, type ReactNode } from "react";
import { FONT_FILES, ROLE_DEFAULTS, type BalloonShape, type FontName, type Measure, type RoleName, type RoleStyle } from "@lettering-engine";
import { FieldLabel, TextField } from "../ui/Field";
import { useI18n } from "../../i18n";
import { LetteringSwatch } from "./LetteringSwatch";
import { VOICES, sameStyle, voiceStyle } from "./letteringVoices";

const shapes: Record<BalloonShape, string> = { balloon: "Speech balloon", ellipse: "Oval", cloud: "Thought cloud", burst: "Shout · burst", whisper: "Whisper · dashed", wavy: "Wavy · weak voice", electric: "Radio · electric", round: "Rounded rectangle", box: "Rectangle", none: "Text only" };
const shapeOrder: BalloonShape[] = ["balloon", "ellipse", "cloud", "burst", "whisper", "wavy", "electric", "round", "box", "none"];
const EFFECT_KEYS = ["halo_width", "shadow", "gradient_color", "warp", "jitter", "skew"] as const;

interface Props {
  value: RoleStyle;
  onChange: (style: RoleStyle) => void;
  role: RoleName;
  idPrefix?: string;
  /** The book's style for this role. Voices restyle it; its own tile returns to it. */
  base?: RoleStyle;
  baseLabel?: string;
  onUseBase?: () => void;
  /** Previews need the bundled faces loaded. */
  measure?: Measure | null;
  sample?: string;
}
export function LetteringStyleControls({ value, onChange, role, idPrefix = "lettering", base, baseLabel = "Book style", onUseBase, measure, sample = "" }: Props) {
  const { t } = useI18n();
  const style = { ...ROLE_DEFAULTS, ...value };
  const patch = <K extends keyof RoleStyle>(key: K, next: RoleStyle[K]) => onChange({ ...style, [key]: next });
  const id = (key: string) => `${idPrefix}-${key}`;
  const shaped = style.shape !== "none", pointing = (role === "speech" || role === "thought") && shaped;
  const effectsActive = EFFECT_KEYS.some(key => style[key] !== ROLE_DEFAULTS[key]) || style.text_stroke_width > 0;
  const size = (key: "max_font_size" | "min_font_size", n: number) => onChange(key === "max_font_size"
    ? { ...style, max_font_size: n, min_font_size: Math.min(n, style.min_font_size) }
    : { ...style, min_font_size: n, max_font_size: Math.max(n, style.max_font_size) });
  const voices = VOICES[role];
  const voiceBase = base ?? style;
  return <div className="lettering-style-controls">
    {measure && <Section title={t("Voice")} hint={t("How the words are said. Voices restyle this book’s lettering.")}>
      <div className="lettering-tile-grid is-voices" role="radiogroup" aria-label={t("Voice")}>
        {base && <Tile label={t(baseLabel)} hint={t("This book’s own lettering for this role")} checked={sameStyle(style, base)} onSelect={() => onUseBase ? onUseBase() : onChange(base)}>
          <LetteringSwatch role={role} style={base} text={sample} measure={measure} />
        </Tile>}
        {voices.map(voice => {
          const next = voiceStyle(voiceBase, voice);
          return <Tile key={voice.id} label={t(voice.label)} hint={t(voice.hint)} checked={sameStyle(style, next)} onSelect={() => onChange(next)}>
            <LetteringSwatch role={role} style={next} text={sample} measure={measure} />
          </Tile>;
        })}
      </div>
    </Section>}

    <Section title={t("Balloon")}>
      <div className="lettering-tile-grid is-shapes" role="radiogroup" aria-label={t("Shape")}>
        {shapeOrder.map(shape => <Tile key={shape} label={t(shapes[shape])} compact checked={style.shape === shape} onSelect={() => patch("shape", shape)}>
          {measure ? <LetteringSwatch role={role} style={{ ...style, shape, ...effectFree }} text={role === "sfx" ? "Aa" : "Hi!"} measure={measure} tail={false} /> : <span className="lettering-tile-fallback">{t(shapes[shape])}</span>}
        </Tile>)}
      </div>
      {shaped && <div className="lettering-field-pair">
        <InkField id={id("fill")} label={t("Fill")} value={style.fill} optional onChange={color => patch("fill", color)} fallback="#ffffff" />
        <InkField id={id("stroke")} label={t("Border")} value={style.stroke} optional onChange={color => patch("stroke", color)} fallback="#181818" />
      </div>}
      {shaped && <div className="lettering-field-pair">
        <Slider id={id("stroke_width")} label={t("Border width")} min={0} max={12} step={.2} value={style.stroke_width} onChange={n => patch("stroke_width", n)} />
        {style.shape === "box" || style.shape === "round"
          ? <Slider id={id("corner_radius")} label={t("Corners")} min={0} max={80} step={1} value={style.corner_radius} onChange={n => patch("corner_radius", n)} />
          : pointing ? <Slider id={id("tail_width")} label={t("Tail width")} min={.4} max={2.5} step={.05} value={style.tail_width} format={n => `${Math.round(n * 100)}%`} onChange={n => patch("tail_width", n)} /> : <span />}
      </div>}
    </Section>

    <Section title={t("Letters")}>
      <div className="lettering-font-grid" role="radiogroup" aria-label={t("Font")}>
        {(Object.keys(FONT_FILES) as FontName[]).map(font => <button key={font} type="button" role="radio" aria-checked={style.font === font} className="lettering-font" style={{ fontFamily: `"${font}"` }} onClick={() => patch("font", font)}>{font}</button>)}
      </div>
      <div className="lettering-field-pair">
        <div><FieldLabel htmlFor={id("max_font_size")}>{t("Size")}</FieldLabel><NumberField id={id("max_font_size")} min={12} max={180} step={1} value={style.max_font_size} onChange={n => size("max_font_size", n)} /></div>
        <Segmented label={t("Weight")} value={String(style.font_weight)} onChange={v => patch("font_weight", Number(v) as 400 | 700)} options={[["400", t("Regular")], ["700", t("Bold")]]} />
      </div>
      <div className="lettering-field-pair">
        <Segmented label={t("Capitals")} value={style.text_case} onChange={v => patch("text_case", v as RoleStyle["text_case"])} options={[["as_written", "Aa", t("As written")], ["upper", "AA", t("All capitals, the classic comic hand")]]} />
        <Segmented label={t("Alignment")} value={style.align} onChange={v => patch("align", v as RoleStyle["align"])} options={[["left", <AlignGlyph key="l" align="left" />, t("left")], ["center", <AlignGlyph key="c" align="center" />, t("center")], ["right", <AlignGlyph key="r" align="right" />, t("right")]]} />
      </div>
      <div className="lettering-field-pair">
        <InkField id={id("color")} label={t("Text color")} value={style.color} onChange={color => patch("color", color)} fallback="#181818" />
        <InkField id={id("gradient_color")} label={t("Fade to")} value={style.gradient_color} optional onChange={color => patch("gradient_color", color)} fallback="#ff7a1a" />
      </div>
      <p className="lettering-hint">{t("Wrap words in *asterisks* to stress them in bold italic.")}</p>
    </Section>

    <details className="lettering-style-group" open={effectsActive || undefined}>
      <summary>{t("Effects")}{effectsActive && <span className="lettering-dot" aria-label={t("in use")} />}</summary>
      <div className="lettering-style-group-body">
        <div className="lettering-field-pair">
          <InkField id={id("text_stroke")} label={t("Letter outline")} value={style.text_stroke} optional onChange={color => patch("text_stroke", color)} fallback="#181818" />
          <Slider id={id("text_stroke_width")} label={t("Outline width")} min={0} max={12} step={.2} value={style.text_stroke_width} onChange={n => patch("text_stroke_width", n)} />
        </div>
        <div className="lettering-field-pair">
          <InkField id={id("halo_color")} label={shaped ? t("Outer outline") : t("Second outline")} value={style.halo_color} optional onChange={color => onChange({ ...style, halo_color: color, halo_width: color !== "transparent" && !style.halo_width ? 2 : style.halo_width })} fallback="#ffffff" />
          <Slider id={id("halo_width")} label={t("Outline reach")} min={0} max={16} step={.2} value={style.halo_width} onChange={n => patch("halo_width", n)} />
        </div>
        <Segmented label={shaped ? t("Balloon shadow") : t("Letter shadow")} value={style.shadow} onChange={v => patch("shadow", v as RoleStyle["shadow"])} options={[["none", t("None")], ["drop", t("Drop")], ["extrude", t("3D")]]} />
        {style.shadow !== "none" && <>
          <div className="lettering-field-pair">
            <InkField id={id("shadow_color")} label={t("Shadow color")} value={style.shadow_color} onChange={color => patch("shadow_color", color)} fallback="#181818" />
            <ShadowPad x={style.shadow_x} y={style.shadow_y} label={t("Shadow direction")} onChange={(x, y) => onChange({ ...style, shadow_x: x, shadow_y: y })} />
          </div>
          <Slider id={id("shadow_depth")} label={t("Shadow depth")} min={0} max={40} step={.5} value={Math.round(Math.hypot(style.shadow_x, style.shadow_y) * 10) / 10} onChange={n => {
            const angle = Math.atan2(style.shadow_y, style.shadow_x) || Math.PI / 4;
            onChange({ ...style, shadow_x: round(Math.cos(angle) * n), shadow_y: round(Math.sin(angle) * n) });
          }} />
        </>}
        <Segmented label={t("Warp")} value={style.warp} onChange={v => patch("warp", v as RoleStyle["warp"])} options={[["none", t("None")], ["arc", t("Arc")], ["wave", t("Wave")]]} />
        {style.warp !== "none" && <Slider id={id("warp_amount")} label={t("Bend")} min={-1} max={1} step={.05} value={style.warp_amount} format={n => `${Math.round(n * 100)}`} onChange={n => patch("warp_amount", n)} />}
        <div className="lettering-field-pair">
          <Slider id={id("jitter")} label={t("Bounce")} min={0} max={1} step={.05} value={style.jitter} format={n => `${Math.round(n * 100)}%`} onChange={n => patch("jitter", n)} />
          <Slider id={id("skew")} label={t("Lean")} min={-30} max={30} step={1} value={style.skew} format={n => `${n}°`} onChange={n => patch("skew", n)} />
        </div>
      </div>
    </details>

    <details className="lettering-style-group">
      <summary>{t("Spacing")}</summary>
      <div className="lettering-style-group-body">
        <div className="lettering-field-pair">
          <Slider id={id("line_height")} label={t("Line spacing")} min={.9} max={2} step={.02} value={style.line_height} onChange={n => patch("line_height", n)} />
          <Slider id={id("padding")} label={t("Inner spacing")} min={0} max={40} step={1} value={style.padding} onChange={n => patch("padding", n)} />
        </div>
        <div className="lettering-field-pair">
          <Slider id={id("letter_spacing")} label={t("Letter spacing")} min={-1} max={12} step={.1} value={style.letter_spacing} onChange={n => patch("letter_spacing", n)} />
          <div><FieldLabel htmlFor={id("min_font_size")}>{t("Minimum size")}</FieldLabel><NumberField id={id("min_font_size")} min={12} max={100} step={.5} value={style.min_font_size} onChange={n => size("min_font_size", n)} /></div>
        </div>
      </div>
    </details>
  </div>;
}
// Shape tiles compare silhouettes, so they leave out shadows and warps.
const effectFree: Partial<RoleStyle> = { shadow: "none", halo_width: 0, warp: "none", jitter: 0, skew: 0 };
const round = (n: number) => Math.round(n * 10) / 10;
function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return <section className="lettering-style-section"><h5 className="lettering-style-heading">{title}</h5>{hint && <p className="lettering-hint">{hint}</p>}{children}</section>;
}
function Tile({ label, hint, checked, onSelect, compact = false, children }: { label: string; hint?: string; checked: boolean; onSelect: () => void; compact?: boolean; children: ReactNode }) {
  return <button type="button" role="radio" aria-checked={checked} title={hint ? `${label} · ${hint}` : label} aria-label={label} className={`lettering-tile ${compact ? "is-compact" : ""}`} onClick={onSelect}>
    <span className="lettering-tile-art">{children}</span>
    {!compact && <span className="lettering-tile-label">{label}</span>}
  </button>;
}
function Segmented({ label, value, options, onChange }: { label: string; value: string; options: [string, ReactNode, string?][]; onChange: (value: string) => void }) {
  const labelId = useId();
  return <div><span id={labelId} className="ui-field-label">{label}</span>
    <div className="lettering-segmented" role="radiogroup" aria-labelledby={labelId}>
      {options.map(([option, content, title]) => <button key={option} type="button" role="radio" aria-checked={value === option} aria-label={title} title={title} onClick={() => onChange(option)}>{content}</button>)}
    </div></div>;
}
function AlignGlyph({ align }: { align: "left" | "center" | "right" }) {
  const x = (width: number) => align === "left" ? 2 : align === "right" ? 18 - width : 10 - width / 2;
  return <svg width="20" height="14" viewBox="0 0 20 14" aria-hidden="true">{[16, 10, 13].map((width, i) => <rect key={i} x={x(width)} y={1 + i * 5} width={width} height="2" fill="currentColor" />)}</svg>;
}
function InkField({ id, label, value, onChange, optional = false, fallback }: { id: string; label: string; value: string; onChange: (color: string) => void; optional?: boolean; fallback: string }) {
  const { t } = useI18n();
  const off = value === "transparent";
  return <div><FieldLabel htmlFor={id}>{label}</FieldLabel>
    <div className={`lettering-ink ${off ? "is-off" : ""}`}>
      <input id={id} type="color" className="lettering-color" value={off ? fallback : value} onChange={e => onChange(e.target.value)} />
      {optional && <label className="lettering-checkbox"><input type="checkbox" checked={off} onChange={e => onChange(e.target.checked ? "transparent" : fallback)} />{t("None")}</label>}
    </div></div>;
}
function Slider({ id, label, min, max, step, value, onChange, format = n => String(round(n)) }: { id: string; label: string; min: number; max: number; step: number; value: number; onChange: (n: number) => void; format?: (n: number) => string }) {
  return <div className="lettering-slider"><div className="lettering-slider-head"><FieldLabel htmlFor={id}>{label}</FieldLabel><span className="lettering-slider-value" aria-hidden="true">{format(value)}</span></div>
    <input id={id} type="range" min={min} max={max} step={step} value={value} aria-valuetext={format(value)} onChange={e => onChange(Number(e.target.value))} /></div>;
}
/** Eight directions the shadow falls; depth is its own slider. */
const DIRECTIONS: [number | null, string][] = [[-3, "Up and left"], [-2, "Up"], [-1, "Up and right"], [4, "Left"], [null, ""], [0, "Right"], [3, "Down and left"], [2, "Down"], [1, "Down and right"]];
function ShadowPad({ x, y, label, onChange }: { x: number; y: number; label: string; onChange: (x: number, y: number) => void }) {
  const { t } = useI18n();
  const depth = Math.max(1, Math.hypot(x, y)), current = (Math.round(Math.atan2(y, x) / (Math.PI / 4)) + 8) % 8;
  return <div><span className="ui-field-label">{label}</span>
    <div className="lettering-shadow-pad" role="radiogroup" aria-label={label}>
      {DIRECTIONS.map(([step, name], i) => step === null ? <span key={i} className="lettering-shadow-origin" aria-hidden="true" /> :
        <button key={i} type="button" role="radio" aria-checked={current === (step + 8) % 8} aria-label={t(name)} title={t(name)} onClick={() => onChange(round(Math.cos(step * Math.PI / 4) * depth), round(Math.sin(step * Math.PI / 4) * depth))} />)}
    </div></div>;
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
