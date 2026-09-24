import type { LetteringStyle, Measure, RoleName } from "@lettering-engine";
import { useI18n } from "../../i18n";
import { LetteringSpecimen, LetteringSwatch } from "./LetteringSwatch";

const ROLE_ORDER: RoleName[] = ["caption", "speech", "thought", "sfx"];
const ROLE_LABELS: Record<RoleName, string> = { caption: "Caption", speech: "Speech", thought: "Thought", sfx: "Sound effect" };
const ROLE_SAMPLES: Record<RoleName, string> = { caption: "Meanwhile…", speech: "Hey!", thought: "Hmm…", sfx: "BAM!" };

/** The four kinds of lettering, each shown in this book's own style. In "add"
 * mode a tile adds that kind at once; in "choose" mode it selects a role. */
export function LetteringRoleTiles({ style, measure, mode, value, disabled, onPick, label }: {
  style: LetteringStyle; measure?: Measure | null; mode: "add" | "choose"; value?: RoleName;
  disabled?: boolean; onPick: (role: RoleName) => void; label: string;
}) {
  const { t } = useI18n();
  return <div className="lettering-tile-grid is-roles" role={mode === "choose" ? "radiogroup" : "group"} aria-label={label}>
    {ROLE_ORDER.map(role => <button key={role} type="button" disabled={disabled} onClick={() => onPick(role)}
      className="lettering-tile" {...(mode === "choose" ? { role: "radio", "aria-checked": value === role } : {})}
      aria-label={mode === "add" ? `${t("Add")} ${t(ROLE_LABELS[role]).toLowerCase()}` : t(ROLE_LABELS[role])}>
      <span className="lettering-tile-art">{measure ? <LetteringSwatch role={role} style={{ ...style.roles[role] }} text={t(ROLE_SAMPLES[role])} measure={measure} /> : null}</span>
      <span className="lettering-tile-label">{t(ROLE_LABELS[role])}</span>
    </button>)}
  </div>;
}

/** Book-wide looks, each previewed as a caption, a balloon and an effect. */
export function LetteringPresetTiles({ presets, value, measure, disabled, onPick }: {
  presets: Record<string, LetteringStyle>; value: string; measure?: Measure | null; disabled?: boolean; onPick: (name: string) => void;
}) {
  const { t } = useI18n();
  const words = { caption: t("Later that night"), speech: t("Who’s *there*?"), sfx: "KRAK!" };
  return <div className="lettering-tile-grid is-presets" role="radiogroup" aria-label={t("Book look")}>
    {Object.entries(presets).map(([name, preset]) => <button key={name} type="button" role="radio" aria-checked={value === name} disabled={disabled}
      className="lettering-tile" aria-label={t(preset.label)} onClick={() => onPick(name)}>
      <span className="lettering-tile-art is-specimen">{measure ? <LetteringSpecimen book={preset} words={words} measure={measure} /> : null}</span>
      <span className="lettering-tile-label">{t(preset.label)}</span>
    </button>)}
  </div>;
}
