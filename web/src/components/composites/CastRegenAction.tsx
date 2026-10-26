import { ErrorNotice } from "./ErrorNotice";
import { useId, useRef, useState, type ComponentProps } from "react";
import { Upload, X } from "lucide-react";
import { useAssetRegenEstimate, useStoryBible } from "../../api/queries";
import { uploadCastReference } from "../../api/pipeline";
import { useReferenceJob } from "../../hooks/useReferenceJob";
import type { CastAssetReference, CastReferenceInput } from "../../types/api";
import { useI18n } from "../../i18n";
import { RegenAction } from "./RegenAction";
import { seriesPath } from "../../api/projectScope";
import { versionedUrl } from "../../lib/assetVersions";

type Props = Omit<ComponentProps<typeof RegenAction>, "onRegenerateWithInstruction"> & {
  projectName: string;
  assetType: CastAssetReference["asset_type"];
  assetId: string;
  stateId?: string;
  onRegenerateWithInstruction: (instruction: string, references: CastReferenceInput[], withLooks: boolean) => void;
};
const referenceKey = (item: CastReferenceInput) => "upload_id" in item
  ? JSON.stringify(["upload", item.upload_id])
  : JSON.stringify([item.asset_type, item.asset_id, item.state_id]);
const ACCEPTED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

function referenceImage(projectName: string, item: CastReferenceInput) {
  if ("upload_id" in item) return `/api${seriesPath(projectName)}/cast/reference-uploads/${encodeURIComponent(item.upload_id)}`;
  return versionedUrl(`/api${seriesPath(projectName)}/files/${assetImage(item)}`);
}

function assetImage(item: CastAssetReference) {
  const id = encodeURIComponent(item.asset_id);
  const state = item.state_id ? encodeURIComponent(item.state_id) : undefined;
  if (item.asset_type === "character") return `refs/${id}/${state ? `states/${state}/` : ""}sheet.png`;
  if (item.asset_type === "location") return `plates/${id}${state ? `/states/${state}` : ""}.png`;
  return `refs/props/${id}/ref.png`;
}

export function CastRegenAction({ projectName, assetType, assetId, stateId, onRegenerateWithInstruction, ...props }: Props) {
  const { t } = useI18n();
  const selectId = useId();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploadLabels, setUploadLabels] = useState<Record<string, string>>({});
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<Error | string | null>(null);
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
  const labelFor = (item: CastReferenceInput) => "upload_id" in item
    ? uploadLabels[item.upload_id] ?? t("Uploaded image")
    : choices.find((choice) => referenceKey(choice) === referenceKey(item))?.label ?? item.asset_id;
  const available = choices.filter((item) => !selected.some((attachment) => referenceKey(attachment) === referenceKey(item)));
  const { data: capabilities } = useAssetRegenEstimate(projectName, assetType, assetId, stateId);
  const { data: estimate } = useAssetRegenEstimate(projectName, assetType, assetId, stateId, true, selected.length);

  const uploadImage = async (file: File | undefined) => {
    if (!file) return;
    if (!ACCEPTED_IMAGE_TYPES.has(file.type)) return setUploadError(t("Use a PNG, JPG, or WebP image."));
    if (file.size > MAX_IMAGE_BYTES) return setUploadError(t("Reference images must be 10 MB or smaller."));
    setUploadError(null);
    setUploading(true);
    try {
      const upload = await uploadCastReference(projectName, file);
      setUploadLabels((labels) => ({ ...labels, [upload.upload_id]: upload.label }));
      if (!selected.some((item) => "upload_id" in item && item.upload_id === upload.upload_id)) {
        setSelection([...selected, { upload_id: upload.upload_id }]);
      }
    } catch (error) {
      setUploadError(error instanceof Error ? error : new Error(t("The image could not be uploaded.")));
    } finally {
      setUploading(false);
    }
  };

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
          <img src={referenceImage(projectName, item)} alt="" className="h-12 w-14 shrink-0 object-contain" />
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
        <div className="space-y-3 pb-3">
          <p className="font-body text-xs leading-5 text-ink-muted">{t("Attach any image, then describe how it should guide the change.")}</p>
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" tabIndex={-1} aria-hidden="true"
            onChange={(event) => { void uploadImage(event.target.files?.[0]); event.target.value = ""; }} />
          <button type="button" disabled={props.busy || props.disabled || uploading} onClick={() => fileRef.current?.click()}
            className="flex min-h-11 w-full items-center justify-center gap-2 border-2 border-dashed border-ink-black/30 bg-bristol px-3 font-body text-sm text-ink-black hover:border-ink-black/60 focus-visible:outline-2 focus-visible:outline-hero-red disabled:opacity-50">
            <Upload size={16} aria-hidden="true" />
            {uploading ? t("Uploading…") : t("Upload an image")}
          </button>
          {uploadError && <ErrorNotice error={uploadError} operation="upload" />}
          {available.length > 0 && <div>
            <label htmlFor={selectId} className="block font-body text-xs text-ink-muted">{t("Or choose one from this project")}</label>
            <select id={selectId} value="" disabled={props.busy || props.disabled}
              onChange={(event) => {
                const item = choices.find((choice) => referenceKey(choice) === event.target.value);
                if (item) setSelection([...selected, { asset_type: item.asset_type, asset_id: item.asset_id, state_id: item.state_id }]);
              }}
              className="mt-1 min-h-11 w-full min-w-0 border-2 border-ink-black/25 bg-bristol px-2 font-body text-sm text-ink-black focus-visible:outline-2 focus-visible:outline-hero-red disabled:opacity-50">
              <option value="">{t("Choose an image…")}</option>
              {available.map((item) => <option key={referenceKey(item)} value={referenceKey(item)}>{item.label}</option>)}
            </select>
          </div>}
        </div>
      </details>}
    </div>}
    instructionSummary={selected.length > 0 ? <div className="mb-3 font-body text-sm">
      <p>{t("Attached references")}</p>
      <ul className="mt-1 list-disc space-y-1 pl-5">{selected.map((item) => <li key={referenceKey(item)}>{labelFor(item)}</li>)}</ul>
    </div> : undefined}
    looks={stateId ? null : capabilities?.looks}
    onRegenerateWithInstruction={(instruction, withLooks) => onRegenerateWithInstruction(instruction, selected, withLooks)}
  />;
}
