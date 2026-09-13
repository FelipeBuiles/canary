import { useId, useState, type ComponentProps } from "react";
import { X } from "lucide-react";
import { useAssetRegenEstimate, useStoryBible } from "../../api/queries";
import { useReferenceJob } from "../../hooks/useReferenceJob";
import type { CastReferenceInput } from "../../types/api";
import { useI18n } from "../../i18n";
import { RegenAction } from "./RegenAction";

type Props = Omit<ComponentProps<typeof RegenAction>, "onRegenerateWithInstruction"> & {
  projectName: string;
  assetType: CastReferenceInput["asset_type"];
  assetId: string;
  stateId?: string;
  onRegenerateWithInstruction: (instruction: string, references: CastReferenceInput[]) => void;
};
const referenceKey = (item: CastReferenceInput) => JSON.stringify([item.asset_type, item.asset_id, item.state_id]);

function referenceImage(item: CastReferenceInput) {
  const id = encodeURIComponent(item.asset_id);
  const state = item.state_id ? encodeURIComponent(item.state_id) : undefined;
  if (item.asset_type === "character") return `refs/${id}/${state ? `states/${state}/` : ""}sheet.png`;
  if (item.asset_type === "location") return `plates/${id}${state ? `/states/${state}` : ""}.png`;
  return `refs/props/${id}/ref.png`;
}

export function CastRegenAction({ projectName, assetType, assetId, stateId, onRegenerateWithInstruction, ...props }: Props) {
  const { t } = useI18n();
  const selectId = useId();
  const { data: bible } = useStoryBible(projectName);
  const { referenceDraft } = useReferenceJob(projectName, assetType === "character" ? "char_id" : assetType === "location" ? "loc_id" : "prop_id", assetId, stateId);
  const [selection, setSelection] = useState<CastReferenceInput[] | null>(null);
  const selected = selection ?? referenceDraft ?? [];
  const choices = (["character", "location", "prop"] as const).flatMap((kind) => {
    const entities = kind === "character" ? bible?.characters : kind === "location" ? bible?.locations : bible?.props;
    return (entities ?? []).flatMap((entity) => [
      { asset_type: kind, asset_id: entity.id, label: entity.name, state_id: undefined as string | undefined },
      ...(kind === "prop" ? [] : ("appearance_states" in entity ? entity.appearance_states ?? [] : []).filter((state) => state.visually_significant).map((state) => ({
        asset_type: kind, asset_id: entity.id, state_id: state.id, label: `${entity.name} · ${state.label}`,
      }))),
    ]);
  }).filter((item) => !(item.asset_type === assetType && item.asset_id === assetId && item.state_id === stateId));
  const labelFor = (item: CastReferenceInput) => choices.find((choice) => referenceKey(choice) === referenceKey(item))?.label ?? item.asset_id;
  const available = choices.filter((item) => !selected.some((attachment) => referenceKey(attachment) === referenceKey(item)));
  const { data: capabilities } = useAssetRegenEstimate(projectName, assetType, assetId, stateId);
  const { data: estimate } = useAssetRegenEstimate(projectName, assetType, assetId, stateId, true, selected.length);

  const instructionPlaceholder = t(assetType === "character"
    ? "Change their appearance, outfit, expression or mood…"
    : assetType === "location"
      ? "Redesign the space, replace furniture, or change the mood…"
      : "Change its shape, materials, color or details…");

  return <RegenAction {...props}
    instructionPlaceholder={instructionPlaceholder}
    instructionCost={selected.length === 0 || estimate?.reference_assets_supported ? estimate?.instruction_estimate : undefined}
    instructionControls={<div className="my-2">
      {selected.length > 0 && estimate && !estimate.reference_assets_supported && <p role="alert" className="font-body text-sm text-hero-red">{t("Reference attachments are temporarily unavailable. Refresh before trying again.")}</p>}
      {selected.length > 0 && <ul aria-label={t("Attached references")} className="space-y-2">
        {selected.map((item) => <li key={referenceKey(item)} className="flex min-w-0 items-center gap-2 bg-surface-container p-2">
          <img src={`/api/projects/${encodeURIComponent(projectName)}/files/${referenceImage(item)}`} alt="" className="h-12 w-14 shrink-0 object-contain" />
          <span className="min-w-0 flex-1 break-words font-body text-xs leading-5 text-ink-black">{labelFor(item)}</span>
          <button type="button" disabled={props.busy || props.disabled} aria-label={`${t("Remove reference")} · ${labelFor(item)}`}
            onClick={() => setSelection(selected.filter((attachment) => referenceKey(attachment) !== referenceKey(item)))}
            className="flex h-11 w-11 shrink-0 items-center justify-center text-ink-muted hover:text-ink-black focus-visible:outline-2 focus-visible:outline-hero-red disabled:opacity-50">
            <X size={16} aria-hidden="true" />
          </button>
        </li>)}
      </ul>}
      {selected.length < 3 && capabilities?.reference_assets_supported && <details>
        <summary className="min-h-11 cursor-pointer py-3 font-body text-xs text-ink-muted underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-hero-red">
          {t("Add a reference")}
        </summary>
        <div className="pb-3">
          <label htmlFor={selectId} className="block font-body text-sm text-ink-black">{t("Choose a reference")}</label>
          <p className="my-1 font-body text-xs leading-5 text-ink-muted">{t("Attach an image from this project, then describe how it should guide the change.")}</p>
          <select id={selectId} value="" disabled={props.busy || props.disabled || available.length === 0}
            onChange={(event) => {
              const item = choices.find((choice) => referenceKey(choice) === event.target.value);
              if (item) setSelection([...selected, { asset_type: item.asset_type, asset_id: item.asset_id, state_id: item.state_id }]);
            }}
            className="min-h-11 w-full min-w-0 border-2 border-ink-black/25 bg-bristol px-2 font-body text-sm text-ink-black focus-visible:outline-2 focus-visible:outline-hero-red disabled:opacity-50">
            <option value="">{t("Choose an image…")}</option>
            {available.map((item) => <option key={referenceKey(item)} value={referenceKey(item)}>{item.label}</option>)}
          </select>
        </div>
      </details>}
    </div>}
    instructionSummary={selected.length > 0 ? <div className="mb-3 font-body text-sm">
      <p>{t("Attached references")}</p>
      <ul className="mt-1 list-disc space-y-1 pl-5">{selected.map((item) => <li key={referenceKey(item)}>{labelFor(item)}</li>)}</ul>
    </div> : undefined}
    onRegenerateWithInstruction={(instruction) => onRegenerateWithInstruction(instruction, selected)}
  />;
}
