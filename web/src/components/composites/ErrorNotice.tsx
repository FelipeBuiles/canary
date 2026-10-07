import { Link } from "react-router-dom";
import { useI18n } from "../../i18n";
import { describeError, type ErrorOperation } from "../../lib/errorPresentation";
import { cn } from "../../lib/cn";
import { Button } from "../ui/Button";
import { ErrorDetails } from "./ErrorDetails";
import { StorageLimitNotice } from "./StorageLimitNotice";

interface ErrorNoticeProps {
  error: unknown;
  errorCode?: string | null;
  errorDetail?: string | null;
  operation: ErrorOperation;
  title?: string;
  recovery?: string;
  /** Explicit, provider-free read recovery. Paid actions retain their own consent controls. */
  onRetry?: () => void;
  retryLabel?: string;
  retryDisabled?: boolean;
  className?: string;
}

/** Errors stay beside their controls, with technical evidence behind a disclosure. */
export function ErrorNotice({ error, errorCode, errorDetail, operation, title, recovery, onRetry, retryLabel, retryDisabled, className }: ErrorNoticeProps) {
  const { t } = useI18n();
  const copy = describeError(error, operation, errorCode);
  if (copy.kind === "storage") return <StorageLimitNotice error={error} errorDetail={errorDetail} framed={false} />;
  return <div role="alert" className={cn("my-3 min-w-0 w-full font-body text-sm leading-6 text-ink-black", className)}>
    <p className="font-bold">{t("specific" in copy ? copy.title : title ?? copy.title)}</p>
    {"message" in copy && copy.message && <p className="mt-1 [overflow-wrap:anywhere]">{t(copy.message)}</p>}
    <p className="mt-1 text-ink-muted">{t("specific" in copy ? copy.recovery : recovery ?? copy.recovery)}</p>
    {"href" in copy && copy.href && <Link to={copy.href} className="mt-2 inline-flex min-h-11 items-center font-semibold underline underline-offset-4">{t(copy.linkLabel)}</Link>}
    {onRetry && !("uncertain" in copy && copy.uncertain) && <Button className="mt-2" variant="outline" size="sm" disabled={retryDisabled} onClick={onRetry}>{retryLabel ?? t("Try again")}</Button>}
    <ErrorDetails error={error} detail={errorDetail} code={errorCode} />
  </div>;
}
