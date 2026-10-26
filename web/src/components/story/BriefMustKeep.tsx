import { useState } from "react";
import { ArrowRight, Plus } from "lucide-react";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import type { Character, StoryBible } from "../../types/api";
import { BriefSection } from "../composites/BriefSection";
import { TextAreaField } from "../ui/Field";
import { groupEventsBySequence, groupTurnsByCharacter, strayWords } from "./briefGrouping";
import { narrativeScenes } from "./storyPhrases";

function splitLines(value: string): string[] {
  return value.split("\n");
}

const capClass = "inline-flex h-[1.375rem] min-w-[1.6875rem] shrink-0 items-center justify-center border border-ink-black bg-bristol px-1 font-meta text-[0.6875rem] font-bold tabular-nums";

function StrayNote({ words, onReword }: { words: string[]; onReword?: () => void }) {
  const { t } = useI18n();
  return (
    <span className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1.5 font-meta text-[0.8125rem]">
      <span className="font-semibold text-ink-black">{t("“{word}” looks like a stray word from another language.", { word: words[0] })}</span>
      {onReword && <button type="button" onClick={onReword}
        className="inline-flex min-h-7 items-center border border-ink-black/40 bg-bristol px-2.5 font-medium hover:border-ink-black">{t("Reword")}</button>}
    </span>
  );
}

interface Row {
  text: string;
  skipped: boolean;
  /** Index into the brief's events; absent for a skipped row. */
  event?: number;
}

/**
 * The essential events, grouped under the sequences they most likely belong
 * to. Adapt must place every one; removing one lets the comic skip it.
 */
export function MustHappen({ events, onChange, story, script, onSkippedChange }: {
  events: string[];
  onChange: (events: string[]) => void;
  story: StoryBible;
  script: string | null;
  onSkippedChange?: (count: number) => void;
}) {
  const { t } = useI18n();
  // Skipped rows keep their place, so Undo puts the event back where it was.
  const [skipped, setSkippedState] = useState<{ at: number; text: string }[]>([]);
  const [rewording, setRewording] = useState<number | null>(null);
  function setSkipped(next: { at: number; text: string }[]) {
    setSkippedState(next);
    onSkippedChange?.(next.length);
  }
  const skippedAt = new Map(skipped.map((entry) => [entry.at, entry]));
  const rows: Row[] = [];
  for (let display = 0, event = 0; display < events.length + skipped.length; display += 1) {
    const entry = skippedAt.get(display);
    if (entry) rows.push({ text: entry.text, skipped: true });
    else { rows.push({ text: events[event], skipped: false, event }); event += 1; }
  }
  const keptBefore = (display: number) => rows.slice(0, display).filter((row) => !row.skipped).length;
  const groups = groupEventsBySequence(rows.map((row) => row.text), story);
  const sceneIds = new Set(narrativeScenes(story.scenes).map((scene) => scene.id));

  function remove(display: number) {
    const row = rows[display];
    if (row.event === undefined) return;
    setRewording(null);
    setSkipped([...skipped, { at: display, text: row.text }]);
    onChange(events.filter((_, index) => index !== row.event));
  }
  function undo(display: number) {
    const at = keptBefore(display);
    setSkipped(skipped.filter((entry) => entry.at !== display));
    onChange([...events.slice(0, at), rows[display].text, ...events.slice(at)]);
  }
  function add(afterDisplay: number) {
    const display = afterDisplay + 1;
    const at = keptBefore(display);
    setSkipped(skipped.map((entry) => entry.at >= display ? { ...entry, at: entry.at + 1 } : entry));
    onChange([...events.slice(0, at), "", ...events.slice(at)]);
    setRewording(display);
  }
  function finish(display: number) {
    setRewording(null);
    const row = rows[display];
    if (row.event === undefined || row.text.trim()) return;
    // An event left empty is dropped, not skipped.
    setSkipped(skipped.map((entry) => entry.at > display ? { ...entry, at: entry.at - 1 } : entry));
    onChange(events.filter((_, index) => index !== row.event));
  }

  return (
    <BriefSection id="essential-events" title={t("ESSENTIAL EVENTS")} heading={t("What must happen")} editLabel={t("Edit all")}
      stamp={t("Must keep")} value={events}
      lede={t("The adaptation can't drop any of these. Remove one to let the comic skip it; add one to insist on it.")}
      onChange={(value) => { setSkipped([]); setRewording(null); onChange(splitLines(value)); }}>
      {groups.map((group, groupIndex) => {
        const last = group.items.at(-1) ?? (groups.slice(0, groupIndex).flatMap((earlier) => earlier.items).at(-1) ?? -1);
        return (
          <div key={group.sequence ? `${group.sequence.part_id}-${group.sequence.number}` : "all"}>
            {group.sequence && groups.length > 1 && <div className="mb-1.5 mt-5 flex flex-wrap items-center gap-2.5 first:mt-0">
              <span className="inline-flex h-[1.375rem] items-center border border-ink-black bg-narrator-gold px-1.5 font-meta text-[0.6875rem] font-bold tracking-[0.04em]">{t("SEQ {number}", { number: group.sequence.number })}</span>
              <h4 className="font-display text-[0.9375rem] font-black uppercase tracking-[-0.01em]">{group.sequence.title}</h4>
              <span className="font-meta text-[0.71875rem] text-ink-muted">{t("{count, plural, one {# scene} other {# scenes}}", { count: group.sequence.scenes.filter((id) => sceneIds.has(id)).length })}</span>
            </div>}
            <ol>
              {group.items.map((display) => {
                const row = rows[display];
                const number = String(display + 1).padStart(2, "0");
                const stray = row.skipped ? [] : strayWords(row.text, script);
                if (rewording === display && row.event !== undefined) {
                  const event = row.event;
                  return <li key={display} className="flex gap-3 border-t border-ink-black/8 py-2.5">
                    <span aria-hidden="true" className={capClass}>{number}</span>
                    <div className="min-w-0 flex-1">
                      <TextAreaField autoFocus rows={3} value={row.text} aria-label={t("Event {number}", { number })}
                        placeholder={t("Something the comic must show")}
                        onChange={(input) => onChange(events.map((item, index) => index === event ? input.target.value : item))}
                        onKeyDown={(input) => { if (input.key === "Escape") { input.preventDefault(); finish(display); } }} />
                      <button type="button" onClick={() => finish(display)}
                        className="mt-2 inline-flex min-h-8 items-center bg-ink-black px-3 font-meta text-[0.8125rem] font-semibold text-pulp-paper">{t("Done editing")}</button>
                    </div>
                  </li>;
                }
                return <li key={display} className={cn(
                  "group/event relative flex items-start gap-3 border-t border-ink-black/8 py-2 pr-1",
                  stray.length > 0 && "-ml-2.5 bg-narrator-gold/12 pl-2.5 shadow-[inset_3px_0_0_var(--color-narrator-gold)]",
                )}>
                  <span aria-hidden="true" className={cn(capClass, row.skipped && "border-dashed bg-transparent text-ink-muted")}>{number}</span>
                  <span className="min-w-0 flex-1">
                    <span className={cn("block whitespace-pre-wrap break-words font-body text-[0.90625rem] leading-[1.55]", row.skipped && "text-ink-muted line-through decoration-ink-black/35")}>
                      {row.skipped && <span className="sr-only">{t("Can be skipped")}: </span>}{row.text}
                    </span>
                    {stray.length > 0 && <StrayNote words={stray} onReword={() => setRewording(display)} />}
                  </span>
                  {row.skipped ? <span className="flex shrink-0 items-center gap-1 font-meta text-xs text-ink-muted">
                    {t("Can be skipped")}
                    <button type="button" onClick={() => undo(display)} aria-label={t("Undo removing event {number}", { number })}
                      className="min-h-7 px-2 font-medium text-ink-black underline underline-offset-2">{t("Undo")}</button>
                  </span> : <span className="flex shrink-0 gap-0.5 transition-opacity [@media(hover:hover)]:absolute [@media(hover:hover)]:right-0 [@media(hover:hover)]:top-1.5 [@media(hover:hover)]:bg-bristol [@media(hover:hover)]:pl-2 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:shadow-[-12px_0_12px_-4px_var(--color-bristol)] group-hover/event:opacity-100 group-focus-within/event:opacity-100">
                    <button type="button" onClick={() => setRewording(display)} aria-label={t("Reword event {number}", { number })}
                      className="min-h-7 border border-transparent px-2 font-meta text-xs font-medium text-ink-soft hover:border-ink-black/30 hover:bg-bristol hover:text-ink-black">{t("Reword")}</button>
                    <button type="button" onClick={() => remove(display)} aria-label={t("Remove event {number}", { number })}
                      className="min-h-7 border border-transparent px-2 font-meta text-xs font-medium text-ink-soft hover:border-ink-black/30 hover:bg-bristol hover:text-ink-black">{t("Remove")}</button>
                  </span>}
                </li>;
              })}
            </ol>
            <button type="button" onClick={() => add(last)}
              className="mt-1 inline-flex min-h-8 items-center gap-1.5 font-meta text-[0.8125rem] font-medium text-ink-muted hover:text-ink-black">
              <Plus size={13} strokeWidth={2.2} aria-hidden="true" />{t("Add a must-have")}
            </button>
          </div>
        );
      })}
      {groups.length > 1 && <p className="mt-4 font-meta text-[0.71875rem] text-ink-muted">{t("Sequences are suggested from the scene summaries.")}</p>}
    </BriefSection>
  );
}

function initials(name: string): string {
  const parts = name.replace(/[^\p{L}\s-]/gu, "").split(/[\s-]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts.at(-1)![0] : (parts[0] ?? "?").slice(0, 2)).toUpperCase();
}

/** Character turns, grouped under the cast member each one belongs to. */
export function CharacterTurns({ turns, onChange, characters, script }: {
  turns: string[];
  onChange: (turns: string[]) => void;
  characters: Character[];
  script: string | null;
}) {
  const { t } = useI18n();
  const items = turns.filter((turn) => turn.trim());
  const groups = groupTurnsByCharacter(items, characters);
  return (
    <BriefSection id="character-turns" title={t("CHARACTER TURNS")} heading={t("How characters change")} editLabel={t("Edit all")}
      stamp={t("Must keep")} value={turns} lede={t("Each turn has to land on the page.")}
      onChange={(value) => onChange(splitLines(value))}>
      {items.length === 0 ? <p className="font-body text-sm text-ink-muted">{t("Nothing specified yet. Edit to add your direction.")}</p> : groups.map((group) => {
        const name = group.character?.name ?? t("Others");
        return <div key={group.character?.id ?? "others"} className="flex gap-3.5 border-t border-ink-black/8 py-3.5 first:border-t-0">
          <span aria-hidden="true" className="flex h-[2.125rem] w-[2.125rem] shrink-0 items-center justify-center border border-ink-black/20 bg-surface-variant font-display text-[0.8125rem] font-black tracking-[-0.02em]">{group.character ? initials(name) : "·"}</span>
          <div className="min-w-0 flex-1">
            <h4 className="mb-1 font-meta text-[0.8125rem] font-semibold">{name}</h4>
            <ul>
              {group.items.map((index) => {
                const stray = strayWords(items[index], script);
                return <li key={index} className="flex gap-2.5 py-0.5">
                  <ArrowRight size={14} strokeWidth={2} aria-hidden="true" className="mt-1 shrink-0 text-hero-red" />
                  <span className="min-w-0">
                    <span className="block whitespace-pre-wrap break-words font-body text-sm leading-[1.5]">{items[index]}</span>
                    {stray.length > 0 && <StrayNote words={stray} />}
                  </span>
                </li>;
              })}
            </ul>
          </div>
        </div>;
      })}
    </BriefSection>
  );
}

/** Protected language, plus the offered lines the book does not contain. */
export function ExactWords({ lines, unmatched, onChange }: {
  lines: string[];
  unmatched: string[];
  onChange: (lines: string[]) => void;
}) {
  const { t } = useI18n();
  const items = lines.filter((line) => line.trim());
  return (
    <BriefSection id="protected-language" title={t("PROTECTED LANGUAGE")} heading={t("Exact words")} editLabel={t("Edit all")}
      stamp={t("Word for word")} value={lines} lede={t("These lines reach the page exactly as the book has them.")}
      onChange={(value) => onChange(splitLines(value))}>
      {items.length === 0
        ? <p className="font-body text-sm text-ink-muted">{t("No lines yet. Edit to add the book's exact wording.")}</p>
        : <ul className="grid gap-2.5 sm:grid-cols-2">
          {items.map((line, index) => <li key={index}
            className="relative whitespace-pre-wrap break-words border border-ink-black/14 bg-bristol py-3 pl-[1.125rem] pr-4 font-body text-sm leading-[1.5] before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-ink-black">{line}</li>)}
        </ul>}
      {unmatched.length > 0 && <section aria-label={t("Not found in the book")} className="mt-5">
        <h4 className="flex items-center gap-2.5 font-meta text-[0.8125rem] font-semibold">
          <span aria-hidden="true" className="inline-flex h-[1.125rem] min-w-[1.125rem] items-center justify-center border border-ink-black bg-narrator-gold px-1 text-[0.65625rem] font-bold">{unmatched.length}</span>
          {t("Not in the book, so not protected")}
        </h4>
        <p className="mt-1 font-body text-xs leading-5 text-ink-muted">{t("To keep one exactly, add the book's wording above.")}</p>
        <ul className="mt-2.5 space-y-2">
          {unmatched.map((phrase, index) => <li key={index} className="whitespace-pre-wrap break-words border border-dashed border-ink-black/40 bg-bristol px-4 py-3 font-body text-sm leading-[1.5] text-ink-soft">{phrase}</li>)}
        </ul>
      </section>}
    </BriefSection>
  );
}
