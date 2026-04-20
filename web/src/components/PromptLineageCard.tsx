import { useState } from "react";
import type { ImagePrompt, PromptSubject } from "../types/api";
import { CollapsibleSection } from "./ui/CollapsibleSection";
import { EditableText } from "./ui/EditableText";
import { Tag } from "./ui/Tag";
import { ImageModal } from "./ui/ImageModal";

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
}: {
  subject: PromptSubject;
  onSave?: (patch: Partial<PromptSubject>) => void;
  editable: boolean;
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
                onSave={(v) => onSave?.({ identity: v })}
                className="text-[0.75rem]"
              />
              <span className="text-ink-black/45">action</span>
              <EditableText
                value={subject.action}
                onSave={(v) => onSave?.({ action: v })}
                className="text-[0.75rem]"
              />
              <span className="text-ink-black/45">expression</span>
              <EditableText
                value={subject.expression}
                onSave={(v) => onSave?.({ expression: v })}
                className="text-[0.75rem]"
              />
              <span className="text-ink-black/45">position</span>
              <EditableText
                value={subject.position}
                onSave={(v) => onSave?.({ position: v })}
                className="text-[0.75rem]"
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
}: {
  subjects: PromptSubject[];
  onSave?: (newSubjects: PromptSubject[]) => void;
  editable: boolean;
}) {
  if (!subjects?.length) {
    return (
      <div className="py-2 text-[0.72rem] text-ink-black/40 italic">No subjects</div>
    );
  }

  const preview = subjects.map((s) => s.name).join(", ");

  return (
    <CollapsibleSection title="SUBJECTS" preview={preview}>
      <div className="space-y-1">
        {subjects.map((subject, i) => (
          <SubjectRow
            key={subject.character_id ?? i}
            subject={subject}
            onSave={(patch) => {
              const newSubjects = [...subjects];
              newSubjects[i] = { ...subjects[i], ...patch };
              onSave?.(newSubjects);
            }}
            editable={editable}
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
}: {
  title: string;
  value?: string | null;
  onSave?: (v: string) => void;
  editable: boolean;
}) {
  if (!value) return null;

  if (editable) {
    return (
      <CollapsibleSection title={title} defaultExpanded>
        <EditableText
          value={value}
          onSave={onSave ?? (() => {})}
          multiline
          className="w-full text-[0.82rem] leading-6"
        />
      </CollapsibleSection>
    );
  }

  return (
    <CollapsibleSection title={title} preview={value.length > 60 ? value.slice(0, 60) + "…" : value}>
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
}: {
  style?: string | null;
  onSave?: (v: string) => void;
  editable: boolean;
}) {
  if (!style) return null;

  const preview = style.length > 50 ? style.slice(0, 50) + "…" : style;

  if (editable) {
    return (
      <CollapsibleSection title="STYLE" defaultExpanded preview={preview}>
        <EditableText
          value={style}
          onSave={onSave ?? (() => {})}
          multiline
          className="w-full text-[0.82rem] leading-6"
        />
      </CollapsibleSection>
    );
  }

  return (
    <CollapsibleSection title="STYLE" preview={preview}>
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
  const effectiveShowAdvanced = editable || showAdvanced;

  const handleSave = (field: keyof ImagePrompt) => (value: string) => {
    onSave?.({ [field]: value } as Partial<ImagePrompt>);
  };

  const handleSubjectsSave = (newSubjects: PromptSubject[]) => {
    onSave?.({ subjects: newSubjects });
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
      />

      <SubjectsSection
        subjects={prompt.subjects ?? []}
        onSave={handleSubjectsSave}
        editable={editable}
      />

      <FieldSection
        title="COMPOSITION"
        value={prompt.composition}
        onSave={handleSave("composition")}
        editable={editable}
      />

      <FieldSection
        title="SETTING"
        value={prompt.setting}
        onSave={handleSave("setting")}
        editable={editable}
      />

      <FieldSection
        title="LIGHTING"
        value={prompt.lighting}
        onSave={handleSave("lighting")}
        editable={editable}
      />

      <FieldSection
        title="MOOD"
        value={prompt.mood}
        onSave={handleSave("mood")}
        editable={editable}
      />

      {effectiveShowAdvanced && (
        <>
          {prompt.props && prompt.props.length > 0 && (
            <CollapsibleSection title="PROPS" defaultExpanded>
              <div className="flex flex-wrap gap-1">
                {prompt.props.map((prop, i) =>
                  editable ? (
                    <EditableText
                      key={i}
                      value={prop}
                      onSave={(v) => {
                        const newProps = [...prompt.props!];
                        newProps[i] = v;
                        onSave?.({ props: newProps });
                      }}
                      className="text-[0.75rem]"
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
          />

          <CollapsibleSection title="REFERENCE IMAGES" defaultExpanded>
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
