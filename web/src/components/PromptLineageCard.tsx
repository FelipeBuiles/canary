import { useEffect, useRef, useState } from "react";
import type { ImagePrompt, PromptSubject } from "../types/api";
import { CollapsibleSection } from "./ui/CollapsibleSection";
import { EditableText } from "./ui/EditableText";
import { Tag } from "./ui/Tag";
import { ImageModal } from "./ui/ImageModal";
import { cn } from "../lib/cn";
import { renderPanelPromptBody } from "../lib/prompting";

interface PromptLineageCardProps {
  prompt: ImagePrompt;
  onSave?: (patch: Partial<ImagePrompt>) => void;
  mode?: "review" | "edit";
  showAdvanced?: boolean;
  project?: string;
}

function SubjectRow({
  subject,
  onSave,
  editable,
  isHighlighted,
  highlightFrom,
}: {
  subject: PromptSubject;
  onSave?: (patch: Partial<PromptSubject>, key: keyof PromptSubject, previous: string) => void;
  editable: boolean;
  isHighlighted: (key: keyof PromptSubject) => boolean;
  highlightFrom: (key: keyof PromptSubject) => string | null;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border-b border-panel-line last:border-b-0">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center gap-2 py-1.5 text-left hover:bg-ink-black/5 transition-colors"
      >
        <span className="font-display text-[0.82rem] font-bold tracking-[-0.02em]">
          {subject.name}
        </span>
        <span className="text-[0.72rem] text-ink-black/50">
          {expanded ? "▼" : "▶"}
        </span>
      </button>
      {expanded && (
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 pb-2 pl-4 text-[0.75rem]">
          {editable ? (
            <>
              <span className="text-ink-black/45">identity</span>
              <EditableText
                value={subject.identity}
                onSave={(v) => onSave?.({ identity: v }, "identity", subject.identity ?? "")}
                className={cn("text-[0.75rem]")}
                highlightActive={isHighlighted("identity")}
                highlightFrom={highlightFrom("identity")}
              />
              <span className="text-ink-black/45">action</span>
              <EditableText
                value={subject.action}
                onSave={(v) => onSave?.({ action: v }, "action", subject.action ?? "")}
                className={cn("text-[0.75rem]")}
                highlightActive={isHighlighted("action")}
                highlightFrom={highlightFrom("action")}
              />
              <span className="text-ink-black/45">expression</span>
              <EditableText
                value={subject.expression}
                onSave={(v) => onSave?.({ expression: v }, "expression", subject.expression ?? "")}
                className={cn("text-[0.75rem]")}
                highlightActive={isHighlighted("expression")}
                highlightFrom={highlightFrom("expression")}
              />
              <span className="text-ink-black/45">position</span>
              <EditableText
                value={subject.position}
                onSave={(v) => onSave?.({ position: v }, "position", subject.position ?? "")}
                className={cn("text-[0.75rem]")}
                highlightActive={isHighlighted("position")}
                highlightFrom={highlightFrom("position")}
              />
            </>
          ) : (
            <>
              <span className="text-ink-black/45">identity</span>
              <span>{subject.identity}</span>
              <span className="text-ink-black/45">action</span>
              <span>{subject.action}</span>
              <span className="text-ink-black/45">expression</span>
              <span>{subject.expression}</span>
              <span className="text-ink-black/45">position</span>
              <span>{subject.position}</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function SubjectsSection({
  subjects,
  onSave,
  editable,
  storageKey,
  isHighlighted,
  highlightFrom,
}: {
  subjects: PromptSubject[];
  onSave?: (newSubjects: PromptSubject[], changedPath: string, previous: string) => void;
  editable: boolean;
  storageKey?: string;
  isHighlighted: (key: string) => boolean;
  highlightFrom: (key: string) => string | null;
}) {
  if (!subjects?.length) {
    return (
      <div className="py-2 text-[0.72rem] text-ink-black/40 italic">No subjects</div>
    );
  }

  const preview = subjects.map((s) => s.name).join(", ");

  return (
    <CollapsibleSection title="SUBJECTS" preview={preview} storageKey={storageKey}>
      <div className="space-y-1">
        {subjects.map((subject, i) => (
          <SubjectRow
            key={subject.character_id ?? i}
            subject={subject}
            onSave={(patch, key, previous) => {
              const newSubjects = [...subjects];
              newSubjects[i] = { ...subjects[i], ...patch };
              onSave?.(newSubjects, `subjects.${i}.${key}`, previous);
            }}
            editable={editable}
            isHighlighted={(key) => isHighlighted(`subjects.${i}.${key}`)}
            highlightFrom={(key) => highlightFrom(`subjects.${i}.${key}`)}
          />
        ))}
      </div>
    </CollapsibleSection>
  );
}

function FieldSection({
  title,
  value,
  onSave,
  editable,
  storageKey,
  highlighted,
  highlightFrom,
}: {
  title: string;
  value?: string | null;
  onSave?: (v: string) => void;
  editable: boolean;
  storageKey?: string;
  highlighted?: boolean;
  highlightFrom?: string | null;
}) {
  if (!value) return null;

  if (editable) {
    return (
      <CollapsibleSection title={title} defaultExpanded storageKey={storageKey}>
        <EditableText
          value={value}
          onSave={onSave ?? (() => {})}
          multiline
          className="w-full text-[0.82rem] leading-6"
          highlightActive={highlighted}
          highlightFrom={highlightFrom}
        />
      </CollapsibleSection>
    );
  }

  return (
    <CollapsibleSection
      title={title}
      preview={value.length > 60 ? value.slice(0, 60) + "…" : value}
      storageKey={storageKey}
    >
      <p className="text-[0.82rem] leading-6 text-ink-black/75 whitespace-pre-wrap">
        {value}
      </p>
    </CollapsibleSection>
  );
}

function StyleSection({
  style,
  onSave,
  editable,
  storageKey,
  highlighted,
  highlightFrom,
}: {
  style?: string | null;
  onSave?: (v: string) => void;
  editable: boolean;
  storageKey?: string;
  highlighted?: boolean;
  highlightFrom?: string | null;
}) {
  if (!style) return null;

  const preview = style.length > 50 ? style.slice(0, 50) + "…" : style;

  if (editable) {
    return (
      <CollapsibleSection title="STYLE" defaultExpanded preview={preview} storageKey={storageKey}>
        <EditableText
          value={style}
          onSave={onSave ?? (() => {})}
          multiline
          className="w-full text-[0.82rem] leading-6"
          highlightActive={highlighted}
          highlightFrom={highlightFrom}
        />
      </CollapsibleSection>
    );
  }

  return (
    <CollapsibleSection title="STYLE" preview={preview} storageKey={storageKey}>
      <p className="text-[0.82rem] leading-6 text-ink-black/75 whitespace-pre-wrap">
        {style}
      </p>
    </CollapsibleSection>
  );
}

export function PromptLineageCard({
  prompt,
  onSave,
  mode = "review",
  showAdvanced,
  project,
}: PromptLineageCardProps) {
  const editable = mode === "edit";
  const [showAdvancedState, setShowAdvancedState] = useState(false);
  const [selectedRefImage, setSelectedRefImage] = useState<string | null>(null);
  const [highlightedFields, setHighlightedFields] = useState<string[]>([]);
  const [highlightFromMap, setHighlightFromMap] = useState<Record<string, string>>({});
  const highlightTimersRef = useRef(new Map<string, number>());
  const effectiveShowAdvanced = editable || showAdvanced;

  useEffect(() => () => {
    for (const timer of highlightTimersRef.current.values()) {
      window.clearTimeout(timer);
    }
    highlightTimersRef.current.clear();
  }, []);

  const flashFields = (keys: string[], fromValues: Record<string, string>) => {
    if (keys.length === 0) return;
    setHighlightedFields((prev) => Array.from(new Set([...prev, ...keys])));
    setHighlightFromMap((prev) => ({ ...prev, ...fromValues }));
    for (const key of keys) {
      const existing = highlightTimersRef.current.get(key);
      if (existing) window.clearTimeout(existing);
      const timeout = window.setTimeout(() => {
        setHighlightedFields((prev) => prev.filter((item) => item !== key));
        setHighlightFromMap((prev) => {
          const next = { ...prev };
          delete next[key];
          return next;
        });
        highlightTimersRef.current.delete(key);
      }, 4200);
      highlightTimersRef.current.set(key, timeout);
    }
  };

  const isHighlighted = (key: string) => highlightedFields.includes(key);
  const highlightFrom = (key: string) => highlightFromMap[key] ?? null;

  const persistPatch = (
    patch: Partial<ImagePrompt>,
    changedKeys: string[],
    fromValues: Record<string, string> = {},
  ) => {
    const bodyFieldKeys: Array<keyof ImagePrompt> = [
      "subjects",
      "composition",
      "setting",
      "lighting",
      "mood",
      "props",
      "constraints",
    ];
    const shouldRebuildBody =
      !Object.prototype.hasOwnProperty.call(patch, "full_prompt") &&
      bodyFieldKeys.some((key) => Object.prototype.hasOwnProperty.call(patch, key));

    const next = { ...prompt, ...patch };
    const outgoing = shouldRebuildBody
      ? { ...patch, full_prompt: renderPanelPromptBody(next) }
      : patch;
    const highlightKeys = shouldRebuildBody ? [...changedKeys, "full_prompt"] : changedKeys;
    const mergedFromValues = shouldRebuildBody
      ? { ...fromValues, full_prompt: prompt.full_prompt ?? "" }
      : fromValues;
    flashFields(highlightKeys, mergedFromValues);
    onSave?.(outgoing);
  };

  const handleSave = (field: keyof ImagePrompt, changedKey?: string) => (value: string) => {
    const key = changedKey ?? String(field);
    const previous = String(prompt[field] ?? "");
    persistPatch({ [field]: value } as Partial<ImagePrompt>, [key], { [key]: previous });
  };

  const handleSubjectsSave = (newSubjects: PromptSubject[], changedPath: string, previous: string) => {
    persistPatch({ subjects: newSubjects }, [changedPath], { [changedPath]: previous });
  };

  return (
    <div className="space-y-0">
      <div className="flex items-center justify-between px-1 py-2">
        <div className="font-meta text-[0.46rem] tracking-[0.16em] text-ink-black/45 uppercase">
          {prompt.scene_id} / PANEL {String(prompt.panel_number).padStart(2, "0")}
        </div>
        <div className="flex gap-1">
          <Tag>{prompt.width}×{prompt.height}</Tag>
          <Tag>{prompt.steps} steps</Tag>
        </div>
      </div>

      <StyleSection
        style={prompt.style}
        onSave={handleSave("style")}
        editable={editable}
        storageKey="style"
        highlighted={isHighlighted("style")}
        highlightFrom={highlightFrom("style")}
      />

      <SubjectsSection
        subjects={prompt.subjects ?? []}
        onSave={handleSubjectsSave}
        editable={editable}
        storageKey="subjects"
        isHighlighted={isHighlighted}
        highlightFrom={highlightFrom}
      />

      <FieldSection
        title="COMPOSITION"
        value={prompt.composition}
        onSave={handleSave("composition")}
        editable={editable}
        storageKey="composition"
        highlighted={isHighlighted("composition")}
        highlightFrom={highlightFrom("composition")}
      />

      <FieldSection
        title="SETTING"
        value={prompt.setting}
        onSave={handleSave("setting")}
        editable={editable}
        storageKey="setting"
        highlighted={isHighlighted("setting")}
        highlightFrom={highlightFrom("setting")}
      />

      <FieldSection
        title="LIGHTING"
        value={prompt.lighting}
        onSave={handleSave("lighting")}
        editable={editable}
        storageKey="lighting"
        highlighted={isHighlighted("lighting")}
        highlightFrom={highlightFrom("lighting")}
      />

      <FieldSection
        title="MOOD"
        value={prompt.mood}
        onSave={handleSave("mood")}
        editable={editable}
        storageKey="mood"
        highlighted={isHighlighted("mood")}
        highlightFrom={highlightFrom("mood")}
      />

      {effectiveShowAdvanced && (
        <>
          {prompt.props && prompt.props.length > 0 && (
            <CollapsibleSection title="PROPS" defaultExpanded storageKey="props">
              <div className="flex flex-wrap gap-1">
                {prompt.props.map((prop, i) =>
                  editable ? (
                    <EditableText
                      key={i}
                      value={prop}
                      onSave={(v) => {
                        const newProps = [...prompt.props!];
                        const changedKey = `props.${i}`;
                        const previous = newProps[i] ?? "";
                        newProps[i] = v;
                        persistPatch({ props: newProps }, [changedKey], { [changedKey]: previous });
                      }}
                      className={cn("text-[0.75rem]")}
                      highlightActive={isHighlighted(`props.${i}`)}
                      highlightFrom={highlightFrom(`props.${i}`)}
                    />
                  ) : (
                    <Tag key={i}>{prop}</Tag>
                  )
                )}
              </div>
            </CollapsibleSection>
          )}

          <FieldSection
            title="CONSTRAINTS"
            value={prompt.constraints}
            onSave={handleSave("constraints")}
            editable={editable}
            storageKey="constraints"
            highlighted={isHighlighted("constraints")}
            highlightFrom={highlightFrom("constraints")}
          />

          <CollapsibleSection title="REFERENCE IMAGES" defaultExpanded storageKey="refimages">
            <div className="flex flex-wrap gap-1">
              {prompt.reference_image_paths.map((path, i) => {
                const fileName = path.split("/").pop() ?? path;
                const refUrl = project
                  ? `/api/projects/${encodeURIComponent(project)}/files/${path}`
                  : path;
                return (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setSelectedRefImage(refUrl)}
                    className="cursor-pointer hover:opacity-70 transition-opacity"
                  >
                    <Tag>{fileName}</Tag>
                  </button>
                );
              })}
            </div>
          </CollapsibleSection>
        </>
      )}

      {!editable && (
        <button
          type="button"
          onClick={() => setShowAdvancedState((s) => !s)}
          className="mt-2 text-[0.68rem] text-ink-black/40 hover:text-ink-black/60 transition-colors"
        >
          {showAdvancedState ? "▲ Hide advanced" : "▼ Show advanced"}
        </button>
      )}

      <CollapsibleSection title="ASSEMBLED PROMPT" defaultExpanded>
        {editable ? (
          <EditableText
            value={prompt.full_prompt}
            onSave={handleSave("full_prompt")}
            multiline
            className="w-full text-[0.82rem] leading-6"
            highlightActive={isHighlighted("full_prompt")}
            highlightFrom={highlightFrom("full_prompt")}
          />
        ) : (
          <p className="text-[0.82rem] leading-6 text-ink-black/75 whitespace-pre-wrap">
            {prompt.full_prompt}
          </p>
        )}
      </CollapsibleSection>
      {prompt.continuity_note && (
        <CollapsibleSection title="CONTINUITY NOTE" defaultExpanded>
          <p className="text-[0.82rem] leading-6 text-ink-black/75 whitespace-pre-wrap italic">
            {prompt.continuity_note}
          </p>
        </CollapsibleSection>
      )}
      {selectedRefImage && (
        <ImageModal
          isOpen={!!selectedRefImage}
          onClose={() => setSelectedRefImage(null)}
          src={selectedRefImage}
          alt={selectedRefImage.split("/").pop() ?? "Reference image"}
        />
      )}
    </div>
  );
}
