import { Button } from "../ui/Button";
import { Surface } from "../ui/Surface";

export function StaleStageNotice({
  lastProgressAt,
  onContinue,
  onReset,
  continuing,
  resetting,
  stageLabel,
  itemLabel,
}: {
  lastProgressAt: string | null;
  onContinue: () => void;
  onReset: () => void;
  continuing: boolean;
  resetting: boolean;
  stageLabel: string;
  itemLabel: string;
}) {
  const busy = continuing || resetting;
  const lastProgress = lastProgressAt
    ? new Date(lastProgressAt).toLocaleString()
    : null;
  return (
    <Surface tone="gold" border="hard" shadow="none" padding="md" className="mb-4">
      <p className="font-meta text-xs font-bold text-hero-red">STAGE INTERRUPTED</p>
      <p className="mt-2 font-body text-sm">
        {lastProgress ? `Last progress: ${lastProgress}.` : "The server stopped before this stage finished."}
      </p>
      <p className="mt-1 font-body text-sm text-ink-black/70">
        Continue resumes the remaining {itemLabel} and keeps finished work.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button onClick={onContinue} disabled={busy}>
          {continuing ? "CONTINUING…" : `CONTINUE ${stageLabel}`}
        </Button>
        <Button variant="outline" onClick={onReset} disabled={busy}>
          {resetting ? "RESETTING…" : "RESET STAGE"}
        </Button>
      </div>
    </Surface>
  );
}
