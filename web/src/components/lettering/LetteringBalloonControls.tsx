import { textFor, type LetteringElement } from "@lettering-engine";
import { FieldLabel, SelectField } from "../ui/Field";
import { useI18n } from "../../i18n";

export function EmphasisButton({ onToggle, disabled }: { onToggle: () => void; disabled?: boolean }) {
  const { t } = useI18n();
  // Keep the textarea's selection: acting on mouse-down would blur it first.
  return <button type="button" className="lettering-emphasis" disabled={disabled} onMouseDown={event => event.preventDefault()} onClick={onToggle}
    title={t("Stress the selected words in bold italic (Ctrl / ⌘ B)")} aria-label={t("Stress selected words")}><b><i>B</i></b></button>;
}

export function TailCurve({ value, onBegin, onPreview, onCommit }: { value: number; onBegin: () => void; onPreview: (bend: number) => void; onCommit: () => void }) {
  const { t } = useI18n();
  return <div className="lettering-slider">
    <div className="lettering-slider-head"><FieldLabel htmlFor="lettering-tail-bend">{t("Tail curve")}</FieldLabel><span className="lettering-slider-value" aria-hidden="true">{value === 0 ? t("straight") : `${Math.round(value * 100)}`}</span></div>
    <input id="lettering-tail-bend" type="range" min={-1} max={1} step={.05} value={value} aria-valuetext={value === 0 ? t("straight") : `${Math.round(value * 100)}`} onPointerDown={onBegin} onFocus={onBegin} onPointerUp={onCommit} onBlur={onCommit}
      onChange={event => onPreview(Math.abs(+event.target.value) < .05 ? 0 : +event.target.value)} onDoubleClick={() => { onBegin(); onPreview(0); onCommit(); }} />
  </div>;
}

export function BalloonJoin({ current, elements, locale, onJoin }: { current: LetteringElement; elements: LetteringElement[]; locale: string; onJoin: (id: string | null) => void }) {
  const { t } = useI18n();
  // Only earlier balloons can lead, so joins read in order and never loop.
  const index = elements.findIndex(element => element.id === current.id);
  const leads = elements.slice(0, index).map((element, i) => ({ element, number: i + 1 }))
    .filter(({ element }) => element.id === current.link_to || (!element.hidden && (element.role === "speech" || element.role === "thought")));
  if (!leads.length && !current.link_to) return null;
  return <div><FieldLabel htmlFor="lettering-join">{t("Join to balloon")}</FieldLabel>
    <SelectField id="lettering-join" value={current.link_to ?? ""} onChange={event => onJoin(event.target.value || null)}>
      <option value="">{t("Not joined")}</option>
      {leads.map(({ element, number }) => {
        const words = textFor(element, locale).replace(/\*/g, "").trim();
        return <option key={element.id} value={element.id}>{`${number} · ${words.length > 32 ? `${words.slice(0, 31)}…` : words || t("Write some words…")}`}</option>;
      })}
    </SelectField>
    <p className="lettering-hint">{t("One speaker, one breath: joined balloons share a single outline.")}</p>
  </div>;
}
