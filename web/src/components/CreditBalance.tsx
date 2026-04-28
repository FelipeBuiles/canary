import { Link } from "react-router-dom";
import { useCreditBalance } from "../api/queries";
import { cn } from "../lib/cn";

interface CreditBalanceProps {
  className?: string;
}

export function CreditBalance({ className }: CreditBalanceProps) {
  const { data, isLoading } = useCreditBalance();

  const credits = data?.balance_credits ?? 0;
  const isLow = credits < 500;

  return (
    <Link
      to="/credits"
      className={cn(
        "flex items-center justify-between rounded-none border border-bristol/12 bg-bristol/5 px-3 py-2 transition-colors hover:bg-bristol/10",
        className,
      )}
    >
      <span className="font-meta text-[0.54rem] tracking-[0.14em] text-bristol/45">
        CREDITS
      </span>
      {isLoading ? (
        <span className="font-meta text-[0.54rem] tracking-[0.1em] text-bristol/30">…</span>
      ) : (
        <span className={cn(
          "font-meta text-[0.66rem] font-medium tabular-nums tracking-[0.06em]",
          isLow ? "text-hero-red" : "text-bristol/70",
        )}>
          {credits.toLocaleString()}
        </span>
      )}
    </Link>
  );
}
