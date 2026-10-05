import { useId } from "react";
import { useI18n } from "../../i18n";
import { FieldLabel, TextAreaField, TextField } from "../ui/Field";
import type { PartTextInput as PartText } from "../../api/parts";

interface Props {
  value: PartText;
  onChange: (value: PartText) => void;
  withTitle?: boolean;
  disabled?: boolean;
}

/** A part's text comes from an uploaded file or pasted text; a file wins. */
export function PartTextInput({ value, onChange, withTitle = false, disabled = false }: Props) {
  const { t } = useI18n();
  const ids = { title: useId(), file: useId(), text: useId() };
  return (
    <div className="space-y-4">
      {withTitle && (
        <div>
          <FieldLabel htmlFor={ids.title}>{t("Part title (optional)")}</FieldLabel>
          <TextField id={ids.title} value={value.title ?? ""} maxLength={200} disabled={disabled}
            onChange={(event) => onChange({ ...value, title: event.target.value })} />
        </div>
      )}
      <div>
        <FieldLabel htmlFor={ids.file}>{t("Upload a manuscript file")}</FieldLabel>
        <input id={ids.file} type="file" accept=".txt,.md,.markdown,.docx,.epub,.pdf" disabled={disabled}
          className="block w-full font-body text-sm file:mr-4 file:min-h-11 file:border-[2px] file:border-ink-black file:bg-bristol file:px-4 file:font-meta file:text-xs"
          onChange={(event) => onChange({ ...value, file: event.target.files?.[0] ?? null })} />
      </div>
      <div>
        <FieldLabel htmlFor={ids.text}>{t("Or paste the text")}</FieldLabel>
        <TextAreaField id={ids.text} rows={6} value={value.text ?? ""} disabled={disabled || !!value.file}
          onChange={(event) => onChange({ ...value, text: event.target.value })} />
      </div>
      {withTitle && (
        <label className="flex min-h-11 items-center gap-3 font-body text-sm">
          <input type="checkbox" className="h-5 w-5" checked={value.autoSplit ?? true} disabled={disabled}
            onChange={(event) => onChange({ ...value, autoSplit: event.target.checked })} />
          <span>{t("Group long manuscripts into parts at chapter boundaries")}</span>
        </label>
      )}
    </div>
  );
}
