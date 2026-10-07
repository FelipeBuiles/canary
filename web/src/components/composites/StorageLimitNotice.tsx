import { Link } from "react-router-dom";
import { useI18n } from "../../i18n";
import { Surface } from "../ui/Surface";
import { ErrorDetails } from "./ErrorDetails";

export function StorageLimitNotice({ error, errorDetail, showHeading = true, framed = showHeading }: {
  error?: unknown;
  errorDetail?: string | null;
  showHeading?: boolean;
  framed?: boolean;
}) {
  const { t } = useI18n();
  const content = <>
      {showHeading && <h3 className="font-body text-base font-bold text-ink-black">{t("Account storage is full")}</h3>}
      <p className="mt-2 font-body text-sm leading-6 text-ink-black">{t("Your saved work is still available. Free up space before continuing.")}</p>
      <p className="mt-2 font-body text-sm leading-6 text-ink-muted">{t("Delete projects you no longer need from their settings, then return here to try again.")}</p>
      <Link to="/" className="mt-3 inline-flex min-h-11 items-center font-body text-sm font-semibold underline underline-offset-4">
        {t("Manage projects")}
      </Link>
      <ErrorDetails error={error} detail={errorDetail} code="storage_budget_exceeded" />
    </>;
  return framed
    ? <Surface role="alert" tone="pulp" padding="md" border="soft" shadow="none" className="my-4">{content}</Surface>
    : <div role="alert" className="my-4">{content}</div>;
}
