import { Link } from "react-router-dom";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { useStyles } from "../../api/queries";
import { useI18n } from "../../i18n";

interface StyleCalloutProps {
  project: string;
  onPickStyle?: () => void;
}

export function StyleCallout({ project, onPickStyle }: StyleCalloutProps) {
  const { t } = useI18n();
  const { data: stylesData, isLoading } = useStyles(project);

  if (isLoading || stylesData?.active_index != null) return null;

  return (
    <Card tone="gold" className="flex flex-wrap items-center justify-between gap-3 p-4">
      <span className="text-sm font-bold text-ink-black">
        {t("Choose a visual style before generating characters, places, or pages.")}
      </span>
      {onPickStyle ? (
        <Button variant="secondary" onClick={onPickStyle}>
          {t("PICK STYLE")}
        </Button>
      ) : (
        <Link className="inline-flex min-h-11 items-center px-4 font-meta text-sm font-bold underline underline-offset-4" to={`/project/${encodeURIComponent(project)}/styles`}>
          {t("PICK STYLE")}
        </Link>
      )}
    </Card>
  );
}
