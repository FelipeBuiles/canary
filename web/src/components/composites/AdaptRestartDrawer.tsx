import { useI18n } from "../../i18n";
import { ConfirmDrawer, type ConfirmDrawerProps } from "./ConfirmDrawer";

export function AdaptRestartDrawer({ extraBody, ...props }: Omit<ConfirmDrawerProps, "title" | "body" | "confirmLabel">) {
  const { t } = useI18n();
  return <ConfirmDrawer
    {...props}
    title={t("Start adaptation over")}
    confirmLabel={t("Start adaptation over")}
    body={t("Create a fresh comic script from your source, approved brief, selected style, and cast. Your current script, page plan, drawings, and exports will be archived and replaced as you continue.")}
    extraBody={<div className="space-y-3 font-body text-sm leading-6">
      <p>{t("This starts a new work allowance. Previous charges remain. Starting over may still encounter story review findings.")}</p>
      <p>{t("This estimate covers adaptation. Page planning follows automatically and is estimated separately when the new script is ready. Drawing waits for you.")}</p>
      {extraBody}
    </div>}
  />;
}
