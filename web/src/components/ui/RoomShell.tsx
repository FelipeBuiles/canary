import type { ReactNode } from "react";

interface RoomShellProps {
  isLoading?: boolean;
  loadingText?: string;
  isEmpty?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  children?: ReactNode;
}

export function RoomShell({
  isLoading,
  loadingText = "LOADING…",
  isEmpty,
  emptyTitle = "NOT AVAILABLE",
  emptyDescription = "This stage has not been reached yet.",
  children,
}: RoomShellProps) {
  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">
          {loadingText}
        </p>
      </div>
    );
  }

  if (isEmpty) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <div className="text-center">
          <div className="font-display text-[1.5rem] font-bold tracking-[-0.05em] text-ink-black/30">
            {emptyTitle}
          </div>
          <p className="mt-2 text-[0.82rem] text-ink-black/50">
            {emptyDescription}
          </p>
        </div>
      </div>
    );
  }

  return <div className="space-y-5">{children}</div>;
}
