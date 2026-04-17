import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useProjectStatus, useApproveStage } from "../api/queries";
import { useRunAction } from "../hooks/useRunAction";
import { STAGE_DISPLAY_NAMES, STAGE_ORDER } from "../types/api";
import type { StageStatus } from "../types/api";
import { Button } from "../components/ui/Button";
import { Icon } from "../components/ui/Icon";

function stageBadgeStyle(status: StageStatus) {
  if (status === "complete") return "bg-archive-sage text-bristol";
  if (status === "running") return "bg-narrator-gold text-ink-black animate-pulse";
  if (status === "awaiting_review") return "bg-hero-red text-bristol";
  if (status === "failed") return "bg-hero-red text-bristol";
  return "bg-pulp-paper text-ink-black/45";
}

function stageLabel(status: StageStatus) {
  if (status === "complete") return "DONE";
  if (status === "running") return "LIVE";
  if (status === "awaiting_review") return "REVIEW";
  if (status === "failed") return "ERROR";
  return "—";
}

const NAV_ITEMS: { icon: "draft" | "assets" | "styles" | "history" | "export"; label: string; route?: string }[] = [
  { icon: "draft", label: "Drafts" },
  { icon: "assets", label: "Assets" },
  { icon: "styles", label: "Styles", route: "styles" },
  { icon: "history", label: "History" },
  { icon: "export", label: "Export" },
];

export function SideNav() {
  const { name } = useParams();
  const navigate = useNavigate();
  const { data: status } = useProjectStatus(name);
  const { handleRun, isPending } = useRunAction();
  const approveStage = useApproveStage();
  const [collapsed, setCollapsed] = useState(false);

  const handleApprove = (stage: string) => {
    if (!name) return;
    approveStage.mutate({ project: name, stage });
  };

  return (
    <aside className="hidden w-[162px] shrink-0 flex-col border-r-[2px] border-ink-black bg-sidebar-tint md:flex">
      <div className="border-b-[2px] border-ink-black p-4">
        <div className="flex items-start gap-3">
          <div className="h-8 w-8 shrink-0 border-[2px] border-ink-black bg-ink-black" />
          <div className="min-w-0 flex-1">
            <div className="font-display text-[1rem] font-bold leading-none tracking-[-0.04em] truncate">
              {status?.project_name ?? "PROJECT INDEX"}
            </div>
            <div className="mt-1 font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/55">
              {name ? "NOVEL-TO-INK V1.0" : "SELECT A PROJECT"}
            </div>
          </div>
        </div>

        {name && (
          <Button
            onClick={() => handleRun(name)}
            disabled={isPending}
            size="sm"
            className="mt-4 flex w-full items-center justify-center gap-1.5 py-2 font-semibold tracking-[0.14em]"
          >
            <Icon name="plus" size={11} />
            {isPending ? "RUNNING…" : "NEW CHAPTER"}
          </Button>
        )}
      </div>

      <nav aria-label="Project tools" className="flex flex-col border-b-[2px] border-ink-black py-2">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.label}
            type="button"
            className="flex items-center gap-2.5 px-4 py-2 text-left text-ink-black/78 hover:bg-ink-black/5"
            onClick={() => {
              if (item.route && name) navigate(`/project/${name}/${item.route}`);
            }}
          >
            <Icon name={item.icon} size={13} className="text-ink-black/70" />
            <span className="font-body text-[0.78rem]">{item.label}</span>
          </button>
        ))}
      </nav>

      <nav aria-label="Pipeline stages" className="flex-1 overflow-y-auto">
        {name && status ? (
          <div>
            <button
              onClick={() => setCollapsed(!collapsed)}
              aria-expanded={!collapsed}
              className="flex w-full items-center justify-between border-b border-ink-black/15 px-4 py-3"
            >
              <span className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/55">
                PIPELINE
              </span>
              <span className="text-[0.6rem] text-ink-black/40">
                {collapsed ? "▸" : "▾"}
              </span>
            </button>

            {!collapsed && (
              <div>
                {STAGE_ORDER.map((stage) => {
                  const info = status.stages[stage];
                  if (!info) return null;
                  const needsApproval = info.status === "awaiting_review";

                  return (
                    <div
                      key={stage}
                      className="flex items-center gap-2 border-b border-ink-black/10 px-4 py-2"
                    >
                      <span
                        className={`h-3 w-3 shrink-0 border border-ink-black text-[0.35rem] flex items-center justify-center ${stageBadgeStyle(info.status)}`}
                      >
                        ●
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="font-body text-[0.72rem] font-medium truncate">
                          {STAGE_DISPLAY_NAMES[stage]}
                        </div>
                        <div className="font-meta text-[0.42rem] tracking-[0.14em] text-ink-black/45">
                          {stageLabel(info.status)} {info.items_done > 0 ? `${info.items_done}/${info.items_total}` : ""}
                        </div>
                      </div>
                      {needsApproval && (
                        <Button
                          onClick={() => handleApprove(stage)}
                          disabled={approveStage.isPending}
                          size="xs"
                        >
                          APPROVE
                        </Button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ) : (
          <div className="px-4 py-4 font-meta text-[0.62rem] tracking-[0.14em] text-ink-black/40">
            NO PROJECT SELECTED
          </div>
        )}
      </nav>

      <div className="border-t-[2px] border-ink-black px-4 py-4">
        <div className="space-y-2 text-[0.72rem] text-ink-black/78">
          <button type="button" className="flex items-center gap-2 hover:text-ink-black">
            <Icon name="settings" size={12} /> Settings
          </button>
          <button type="button" className="flex items-center gap-2 hover:text-ink-black">
            <Icon name="support" size={12} /> Support
          </button>
        </div>
      </div>
    </aside>
  );
}
