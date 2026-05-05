import type { ReactNode } from "react";
import { useI18n } from "../../i18n";
import { LoadingBlock, StateBlock } from "./StateBlock";

interface RoomShellProps {
  isLoading?: boolean;
  loadingText?: string;
  isEmpty?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  fullHeight?: boolean;
  children?: ReactNode;
}

export function RoomShell({
  isLoading,
  loadingText = "LOADING…",
  isEmpty,
  emptyTitle = "NOT AVAILABLE",
  emptyDescription = "This room is not ready yet.",
  fullHeight,
  children,
}: RoomShellProps) {
  const { t } = useI18n();
  if (isLoading) {
    return <LoadingBlock label={t(loadingText)} />;
  }

  if (isEmpty) {
    return (
      <StateBlock
        title={t(emptyTitle)}
        description={t(emptyDescription)}
        icon="draft"
      />
    );
  }

  return <div className={fullHeight ? "h-full" : "space-y-10"}>{children}</div>;
}
