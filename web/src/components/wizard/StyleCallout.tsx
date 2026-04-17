import { Link } from "react-router-dom";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { useStyles } from "../../api/queries";

interface StyleCalloutProps {
  project: string;
  onPickStyle?: () => void;
}

export function StyleCallout({ project, onPickStyle }: StyleCalloutProps) {
  const { data: stylesData, isLoading } = useStyles(project);

  if (isLoading || stylesData?.active_index != null) return null;

  return (
    <Card tone="gold" className="flex items-center justify-between gap-3 p-3">
      <span className="text-[0.78rem] font-bold text-ink-black">
        No visual style selected — pick one before generating panels for best results.
      </span>
      {onPickStyle ? (
        <Button size="sm" variant="secondary" onClick={onPickStyle}>
          PICK STYLE
        </Button>
      ) : (
        <Link to={`/project/${encodeURIComponent(project)}/styles`}>
          <Button size="sm" variant="secondary">
            PICK STYLE
          </Button>
        </Link>
      )}
    </Card>
  );
}
