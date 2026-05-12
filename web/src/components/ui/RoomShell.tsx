import type { ReactNode } from "react";
import { useI18n } from "../../i18n";
import type { StageName, StageStatus } from "../../types/api";
import { LoadingBlock, StateBlock } from "./StateBlock";
import { StagePlaceholder } from "./StagePlaceholder";

interface RoomShellProps {
  isLoading?: boolean;
  loadingText?: string;
  isEmpty?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  fullHeight?: boolean;
  // When the room is loading because the stage hasn't run yet (pending) or
  // is currently running, pass the stage info to render the rich
  // StagePlaceholder (stage badge + progress) instead of the basic
  // LoadingBlock spinner.
  loadingStage?: StageName;
  loadingStageStatus?: StageStatus;
  loadingStageItemsDone?: number;
  loadingStageItemsTotal?: number;
  children?: ReactNode;
}

export function RoomShell({
  isLoading,
  loadingText = "LOADING…",
  isEmpty,
  emptyTitle = "NOT AVAILABLE",
  emptyDescription = "This room is not ready yet.",
  fullHeight,
  loadingStage,
  loadingStageStatus,
  loadingStageItemsDone,
  loadingStageItemsTotal,
  children,
}: RoomShellProps) {
  const { t } = useI18n();
  if (isLoading) {
    if (
      loadingStage &&
      (loadingStageStatus === "running" || loadingStageStatus === "pending")
    ) {
      return (
        <StagePlaceholder
          stage={loadingStage}
          status={loadingStageStatus}
          itemsDone={loadingStageItemsDone}
          itemsTotal={loadingStageItemsTotal}
        />
      );
    }
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
