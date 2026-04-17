import { useNavigate } from "react-router-dom";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { SectionLabel } from "../SectionLabel";
import { StatRow } from "../ui/StatRow";

interface CompleteStepProps {
  project: string;
  totalCost: number;
  panelCount: number;
}

export function CompleteStep({ project, totalCost, panelCount }: CompleteStepProps) {
  const navigate = useNavigate();

  return (
    <div className="space-y-5">
      <Card tone="ink" className="p-5 md:p-8 text-center">
        <SectionLabel tone="gold">PRODUCTION</SectionLabel>
        <h1 className="mt-4 font-display font-bold text-[clamp(2.5rem,6vw,4.5rem)] leading-[0.82] tracking-[-0.08em] text-narrator-gold">
          COMPLETE
        </h1>
        <p className="mt-4 text-[0.95rem] text-bristol/70 max-w-[40ch] mx-auto">
          Your comic has been assembled and is ready for review in the Compose room.
        </p>
      </Card>

      <Card className="p-5">
        <div className="space-y-2">
          <StatRow label="TOTAL PANELS">{panelCount}</StatRow>
          <StatRow label="TOTAL INK USAGE">${totalCost.toFixed(2)}</StatRow>
        </div>
      </Card>

      <Button
        size="lg"
        onClick={() => navigate(`/project/${encodeURIComponent(project)}/compose`)}
      >
        OPEN IN COMPOSE ROOM
      </Button>
    </div>
  );
}
