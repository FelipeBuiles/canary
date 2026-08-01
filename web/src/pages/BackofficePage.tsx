import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertCircle,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Check,
  CircleCheck,
  CreditCard,
  Download,
  ExternalLink,
  Filter,
  Gauge,
  LayoutDashboard,
  LifeBuoy,
  LockKeyhole,
  Menu,
  MessageCircle,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings2,
  ShieldAlert,
  UserCheck,
  UsersRound,
  X,
  type LucideIcon,
} from "lucide-react";
import { BrandMark } from "../components/BrandMark";
import { Button } from "../components/ui/Button";
import { Surface } from "../components/ui/Surface";
import { cn } from "../lib/cn";
import {
  ANALYTICS_SERIES,
  BACKOFFICE_ACTIVITY,
  BACKOFFICE_TICKETS,
  BACKOFFICE_USERS,
  FUNNEL_STEPS,
  MODEL_SPEND,
  USAGE_SERIES,
  type ActivityItem,
  type BackofficeUser,
  type BackofficeView,
  type SeriesPoint,
  type SupportTicket,
  type TicketPriority,
  type TicketStatus,
  type UserFilter,
  type UserStatus,
} from "./backofficeData";
import "./BackofficePage.css";

type RangeKey = "7d" | "30d" | "90d";
type NoticeTone = "ink" | "red" | "gold" | "sage" | "blue";

const NAV_ITEMS: Array<{ key: BackofficeView; label: string; icon: LucideIcon; shortcut: string }> = [
  { key: "overview", label: "Overview", icon: LayoutDashboard, shortcut: "⌘ 1" },
  { key: "users", label: "Users", icon: UsersRound, shortcut: "⌘ 2" },
  { key: "support", label: "Support queue", icon: LifeBuoy, shortcut: "⌘ 3" },
  { key: "analytics", label: "Analytics", icon: BarChart3, shortcut: "⌘ 4" },
];

const VIEW_META: Record<BackofficeView, { kicker: string; title: string; description: string }> = {
  overview: {
    kicker: "Saturday · August 01, 2026",
    title: "The press is in a good rhythm",
    description: "A quick read on creators, production, and the work that needs an operator’s eye.",
  },
  users: {
    kicker: "Customer directory",
    title: "Users",
    description: "Keep accounts moving, answer the odd edge case, and make the right recovery easy.",
  },
  support: {
    kicker: "Customer care",
    title: "Support queue",
    description: "Small, specific answers keep a long production session from becoming a lost one.",
  },
  analytics: {
    kicker: "Operating picture",
    title: "Analytics",
    description: "See where the press is busy, where creators pause, and what the run is costing.",
  },
};

const AVATAR_TONE: Record<BackofficeUser["avatarTone"], string> = {
  red: "bg-hero-red text-bristol",
  gold: "bg-narrator-gold text-ink-black",
  blue: "bg-secondary-container text-on-secondary-container",
  sage: "bg-chip-sage text-ink-black",
  ink: "bg-ink-black text-bristol",
};

const NOTICE_TONE: Record<NoticeTone, string> = {
  ink: "bg-ink-black text-bristol",
  red: "bg-chip-red text-hero-red",
  gold: "bg-chip-gold text-ink-black",
  sage: "bg-chip-sage text-ink-black",
  blue: "bg-secondary-container text-on-secondary-container",
};

const USER_STATUS: Record<UserStatus, { label: string; tone: NoticeTone }> = {
  active: { label: "Active", tone: "sage" },
  trial: { label: "Trial", tone: "gold" },
  past_due: { label: "Past due", tone: "red" },
  suspended: { label: "Suspended", tone: "ink" },
};

const TICKET_STATUS: Record<TicketStatus, { label: string; tone: NoticeTone }> = {
  open: { label: "Open", tone: "red" },
  waiting: { label: "Waiting", tone: "gold" },
  resolved: { label: "Resolved", tone: "sage" },
};

const PRIORITY_META: Record<TicketPriority, { label: string; tone: NoticeTone }> = {
  urgent: { label: "Urgent", tone: "red" },
  normal: { label: "Normal", tone: "blue" },
  low: { label: "Low", tone: "ink" },
};

function formatMoney(value: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
}

function Avatar({ user, size = "md" }: { user: BackofficeUser; size?: "sm" | "md" | "lg" }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex shrink-0 items-center justify-center border-[2px] border-ink-black font-meta font-bold tracking-[-0.04em]",
        AVATAR_TONE[user.avatarTone],
        size === "sm" && "h-8 w-8 text-[0.52rem]",
        size === "md" && "h-10 w-10 text-[0.62rem]",
        size === "lg" && "h-16 w-16 text-[0.92rem] shadow-paper-sm",
      )}
    >
      {user.initials}
    </span>
  );
}

function StateTag({ label, tone = "ink", className }: { label: string; tone?: NoticeTone; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex min-h-6 items-center gap-1.5 px-2 font-meta text-[0.52rem] font-bold uppercase tracking-[0.1em]",
        NOTICE_TONE[tone],
        className,
      )}
    >
      <span aria-hidden="true" className="h-1.5 w-1.5 bg-current" />
      {label}
    </span>
  );
}

function PageHeading({
  view,
  actions,
}: {
  view: BackofficeView;
  actions?: ReactNode;
}) {
  const meta = VIEW_META[view];

  return (
    <header className="mb-7 flex flex-wrap items-end justify-between gap-5 border-b-[2px] border-ink-black pb-5">
      <div className="min-w-0">
        <div className="mb-2 flex flex-wrap items-center gap-2 font-meta text-[0.58rem] font-bold uppercase tracking-[0.16em] text-ink-muted">
          <span className="bg-narrator-gold px-2 py-1 text-ink-black">{meta.kicker}</span>
          <span className="text-ink-soft">/</span>
          <span>Local operator desk</span>
        </div>
        <h1 className="font-display text-[clamp(2rem,3.5vw,3.7rem)] font-black leading-[0.94] tracking-[-0.045em] text-ink-black">
          {meta.title}
        </h1>
        <p className="mt-3 max-w-[68ch] font-body text-[0.9rem] leading-6 text-ink-muted">{meta.description}</p>
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

function PanelHeading({
  kicker,
  title,
  detail,
  action,
}: {
  kicker?: string;
  title: string;
  detail?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b-[2px] border-ink-black/10 px-5 py-4">
      <div>
        {kicker && <div className="font-meta text-[0.54rem] font-bold uppercase tracking-[0.16em] text-ink-muted">{kicker}</div>}
        <h2 className="mt-1 font-display text-[1.2rem] font-black leading-none tracking-[-0.03em] text-ink-black">{title}</h2>
        {detail && <p className="mt-1.5 font-body text-[0.72rem] leading-5 text-ink-soft">{detail}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

function MetricCell({
  label,
  value,
  detail,
  delta,
  deltaTone = "up",
}: {
  label: string;
  value: string;
  detail: string;
  delta?: string;
  deltaTone?: "up" | "down" | "steady";
}) {
  return (
    <div className="min-h-[126px] border-b-[2px] border-ink-black/10 px-5 py-4 last:border-b-0 md:border-b-0 md:border-r-[2px] md:last:border-r-0">
      <div className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.15em] text-ink-muted">{label}</div>
      <div className="mt-4 flex items-end justify-between gap-3">
        <span className="font-display text-[2.1rem] font-black leading-none tracking-[-0.05em] text-ink-black">{value}</span>
        {delta && (
          <span
            className={cn(
              "mb-0.5 inline-flex items-center gap-0.5 font-meta text-[0.56rem] font-bold tracking-[0.04em]",
              deltaTone === "down" ? "text-hero-red" : deltaTone === "steady" ? "text-ink-soft" : "text-archive-sage",
            )}
          >
            {deltaTone === "down" ? <ArrowDownRight size={12} /> : deltaTone === "steady" ? <Activity size={11} /> : <ArrowUpRight size={12} />}
            {delta}
          </span>
        )}
      </div>
      <p className="mt-2 font-body text-[0.67rem] font-semibold text-ink-soft">{detail}</p>
    </div>
  );
}

function UsageChart({ points, compact = false }: { points: SeriesPoint[]; compact?: boolean }) {
  const width = 760;
  const height = compact ? 190 : 240;
  const left = 38;
  const right = 16;
  const top = 14;
  const bottom = compact ? 28 : 36;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const x = (index: number) => left + (points.length <= 1 ? plotWidth / 2 : (index / (points.length - 1)) * plotWidth);
  const y = (value: number) => top + plotHeight - (value / 100) * plotHeight;
  const primaryPath = points.map((point, index) => `${index === 0 ? "M" : "L"} ${x(index).toFixed(2)} ${y(point.value).toFixed(2)}`).join(" ");
  const secondaryPath = points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${x(index).toFixed(2)} ${y(point.secondary ?? point.value * 0.65).toFixed(2)}`)
    .join(" ");
  const areaPath = `${primaryPath} L ${x(points.length - 1).toFixed(2)} ${(height - bottom).toFixed(2)} L ${x(0).toFixed(2)} ${(height - bottom).toFixed(2)} Z`;

  return (
    <div className="min-w-0 px-4 pb-4 pt-3 md:px-5">
      <svg
        className="backoffice-chart h-auto w-full overflow-visible"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Daily active creators and AI calls"
      >
        <title>Daily active creators and AI calls</title>
        {[0, 25, 50, 75, 100].map((tick) => (
          <g key={tick}>
            <line x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} stroke="var(--color-ink-black)" strokeOpacity="0.1" strokeWidth="1" />
            <text x={left - 10} y={y(tick) + 3} textAnchor="end" fill="var(--color-ink-black)" fontFamily="var(--font-meta)" fontSize="10">
              {tick}
            </text>
          </g>
        ))}
        <path d={areaPath} fill="var(--color-chip-red)" fillOpacity="0.55" />
        <path d={secondaryPath} fill="none" stroke="var(--color-ink-black)" strokeDasharray="4 6" strokeLinecap="square" strokeWidth="2" strokeOpacity="0.5" />
        <path d={primaryPath} fill="none" stroke="var(--color-hero-red)" strokeLinecap="square" strokeLinejoin="miter" strokeWidth="3" />
        {points.map((point, index) => (
          <g key={`${point.label}-${index}`}>
            <circle cx={x(index)} cy={y(point.value)} r="4" fill="var(--color-bristol)" stroke="var(--color-hero-red)" strokeWidth="3" />
            <title>{`${point.label}: ${point.value} active creators`}</title>
            <text x={x(index)} y={height - 10} textAnchor="middle" fill="var(--color-ink-black)" fontFamily="var(--font-meta)" fontSize="10">
              {point.label}
            </text>
          </g>
        ))}
      </svg>
      <div className="mt-1 flex flex-wrap items-center gap-x-5 gap-y-2 px-9 font-meta text-[0.52rem] font-bold uppercase tracking-[0.12em] text-ink-muted">
        <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 bg-hero-red" /> Active creators</span>
        <span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 border-[2px] border-ink-black/55" /> AI calls</span>
      </div>
    </div>
  );
}

function ActivityFeed({ items }: { items: ActivityItem[] }) {
  const activityClass: Record<ActivityItem["tone"], string> = {
    red: "bg-hero-red",
    gold: "bg-narrator-gold",
    sage: "bg-archive-sage",
    blue: "bg-secondary-container",
    ink: "bg-ink-black",
  };

  return (
    <div className="space-y-1 px-5 py-3">
      {items.map((item) => (
        <div key={item.id} className="flex gap-3 py-3">
          <span aria-hidden="true" className={cn("mt-1.5 h-2.5 w-2.5 shrink-0 border-[2px] border-ink-black", activityClass[item.tone])} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="font-body text-[0.76rem] font-bold text-ink-black">{item.title}</p>
              <time className="font-meta text-[0.5rem] uppercase tracking-[0.1em] text-ink-soft">{item.time}</time>
            </div>
            <p className="mt-1 truncate font-body text-[0.68rem] text-ink-soft">{item.detail}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function OverviewView({
  range,
  onRangeChange,
  onViewChange,
  onRefresh,
  users,
  tickets,
}: {
  range: RangeKey;
  onRangeChange: (range: RangeKey) => void;
  onViewChange: (view: BackofficeView) => void;
  onRefresh: () => void;
  users: BackofficeUser[];
  tickets: SupportTicket[];
}) {
  const attentionUsers = users.filter((user) => user.status === "past_due" || user.status === "suspended");
  const openTickets = tickets.filter((ticket) => ticket.status !== "resolved");
  const chartPoints = USAGE_SERIES[range];

  return (
    <>
      <PageHeading
        view="overview"
        actions={
          <>
            <button
              type="button"
              onClick={onRefresh}
              className="inline-flex min-h-11 items-center gap-2 border-[2px] border-ink-black/18 bg-bristol px-3.5 font-meta text-[0.64rem] font-bold uppercase tracking-[0.1em] text-ink-black transition-colors hover:border-ink-black hover:bg-surface-container"
            >
              <RefreshCw size={14} />
              Refresh
            </button>
            <Button size="sm" onClick={() => onViewChange("support")}>
              <LifeBuoy size={14} />
              Open queue
            </Button>
          </>
        }
      />

      <Surface border="soft" shadow="none" className="grid grid-cols-2 overflow-hidden md:grid-cols-4">
        <MetricCell label="Active creators" value="1,284" detail="last 30 days" delta="12.4%" />
        <MetricCell label="Running jobs" value="18" detail="3 need a look" delta="4" deltaTone="steady" />
        <MetricCell label="Support queue" value={String(openTickets.length)} detail="2 urgent · 1 waiting" delta="2" deltaTone="down" />
        <MetricCell label="Credits this week" value="8.7k" detail="customer usage" delta="18.6%" />
      </Surface>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(320px,0.75fr)]">
        <Surface border="soft" shadow="none" className="min-w-0 overflow-hidden">
          <PanelHeading
            kicker="Usage pulse"
            title="Creators at work"
            detail="Unique active creators and AI calls, indexed to the last 30 days."
            action={
              <select
                aria-label="Usage chart date range"
                value={range}
                onChange={(event) => onRangeChange(event.target.value as RangeKey)}
                className="h-9 border-[2px] border-ink-black/18 bg-pulp-paper px-2 font-meta text-[0.56rem] font-bold uppercase tracking-[0.1em] text-ink-black outline-none hover:border-ink-black focus:border-hero-red"
              >
                <option value="7d">Last 7 days</option>
                <option value="30d">Last 30 days</option>
                <option value="90d">Last 90 days</option>
              </select>
            }
          />
          <UsageChart points={chartPoints} />
          <div className="grid grid-cols-3 border-t-[2px] border-ink-black/10 bg-surface-container">
            <div className="px-4 py-3"><div className="font-meta text-[0.5rem] uppercase tracking-[0.12em] text-ink-muted">Peak day</div><div className="mt-1 font-display text-[1.25rem] font-black">Saturday</div></div>
            <div className="border-l-[2px] border-ink-black/10 px-4 py-3"><div className="font-meta text-[0.5rem] uppercase tracking-[0.12em] text-ink-muted">Avg. session</div><div className="mt-1 font-display text-[1.25rem] font-black">24m</div></div>
            <div className="border-l-[2px] border-ink-black/10 px-4 py-3"><div className="font-meta text-[0.5rem] uppercase tracking-[0.12em] text-ink-muted">Export rate</div><div className="mt-1 font-display text-[1.25rem] font-black">17%</div></div>
          </div>
        </Surface>

        <Surface border="soft" shadow="none" className="overflow-hidden">
          <PanelHeading
            kicker="Operator inbox"
            title="Needs attention"
            detail={`${openTickets.length} customer threads are still in motion.`}
            action={
              <button type="button" onClick={() => onViewChange("support")} className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.1em] text-hero-red underline decoration-2 underline-offset-4 hover:text-ink-black">
                View all
              </button>
            }
          />
          <div className="space-y-1 px-4 py-3">
            {openTickets.slice(0, 3).map((ticket) => {
              const user = users.find((candidate) => candidate.id === ticket.userId);
              return (
                <button key={ticket.id} type="button" onClick={() => onViewChange("support")} className="flex w-full items-start gap-3 bg-transparent px-2 py-3 text-left transition-colors hover:bg-surface-container">
                  <span className={cn("mt-1 h-2.5 w-2.5 shrink-0 border-[2px] border-ink-black", ticket.priority === "urgent" ? "bg-hero-red" : "bg-narrator-gold")} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="truncate font-body text-[0.75rem] font-bold text-ink-black">{ticket.subject}</span>
                      <span className="shrink-0 font-meta text-[0.5rem] uppercase tracking-[0.08em] text-ink-soft">{ticket.updated}</span>
                    </span>
                    <span className="mt-1 block truncate font-body text-[0.67rem] text-ink-soft">{user?.name} · {ticket.id}</span>
                  </span>
                </button>
              );
            })}
          </div>
          <div className="border-t-[2px] border-ink-black/10 bg-chip-red px-5 py-3">
            <div className="flex items-center gap-2 font-meta text-[0.56rem] font-bold uppercase tracking-[0.1em] text-hero-red"><AlertCircle size={13} /> 2 tickets have been waiting over 30 minutes</div>
          </div>
        </Surface>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1.25fr)]">
        <Surface border="soft" shadow="none" className="overflow-hidden">
          <PanelHeading kicker="Latest movement" title="Activity feed" detail="Server-confirmed milestones from the last few hours." />
          <ActivityFeed items={BACKOFFICE_ACTIVITY} />
        </Surface>

        <Surface border="soft" shadow="none" className="overflow-hidden">
          <PanelHeading
            kicker="Production floor"
            title="Projects in motion"
            detail="The sessions most likely to need a nudge today."
            action={
              <button type="button" onClick={() => onViewChange("users")} className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.1em] text-hero-red underline decoration-2 underline-offset-4 hover:text-ink-black">
                Browse users
              </button>
            }
          />
          <div role="region" tabIndex={0} aria-label="Projects in motion table; scroll horizontally to see all columns" className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left">
              <thead className="bg-surface-container font-meta text-[0.5rem] font-bold uppercase tracking-[0.12em] text-ink-muted">
                <tr><th className="px-5 py-3">Creator</th><th className="px-3 py-3">Current work</th><th className="px-3 py-3">Credits</th><th className="px-5 py-3 text-right">State</th></tr>
              </thead>
              <tbody className="divide-y-[2px] divide-ink-black/8">
                {users.filter((user) => user.projects > 0).slice(0, 5).map((user) => (
                  <tr key={user.id} className="transition-colors hover:bg-surface-container/70">
                    <td className="px-5 py-3.5"><div className="flex items-center gap-3"><Avatar user={user} size="sm" /><div><div className="font-body text-[0.73rem] font-bold">{user.name}</div><div className="mt-0.5 font-meta text-[0.48rem] uppercase tracking-[0.1em] text-ink-soft">{user.plan}</div></div></div></td>
                    <td className="px-3 py-3.5 font-body text-[0.7rem] font-semibold text-ink-muted">{user.currentStage}</td>
                    <td className="px-3 py-3.5 font-meta text-[0.64rem] font-bold tabular-nums text-ink-black">{user.credits.toLocaleString()}</td>
                    <td className="px-5 py-3.5 text-right"><StateTag label={USER_STATUS[user.status].label} tone={USER_STATUS[user.status].tone} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Surface>
      </div>

      {attentionUsers.length > 0 && (
        <div className="mt-5 flex flex-wrap items-center justify-between gap-4 border-[2px] border-ink-black bg-narrator-gold px-5 py-4 shadow-paper-sm">
          <div className="flex items-start gap-3"><ShieldAlert className="mt-0.5 shrink-0" size={18} /><div><div className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.14em]">Small list, real consequences</div><p className="mt-1 font-body text-[0.78rem] font-semibold">{attentionUsers.length} accounts need a billing or trust decision before they can continue.</p></div></div>
          <Button variant="outline" size="xs" onClick={() => onViewChange("users")}>Review at-risk users <ArrowUpRight size={13} /></Button>
        </div>
      )}
    </>
  );
}

function UsersView({
  users,
  onOpenUser,
  onInvite,
}: {
  users: BackofficeUser[];
  onOpenUser: (userId: string) => void;
  onInvite: () => void;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<UserFilter>("all");

  const filteredUsers = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return users.filter((user) => {
      const matchesQuery = !normalized || `${user.name} ${user.email} ${user.id}`.toLowerCase().includes(normalized);
      const matchesFilter = filter === "all" || (filter === "active" && user.status === "active") || (filter === "trial" && user.status === "trial") || (filter === "attention" && (user.status === "past_due" || user.status === "suspended"));
      return matchesQuery && matchesFilter;
    });
  }, [filter, query, users]);

  return (
    <>
      <PageHeading
        view="users"
        actions={<Button size="sm" onClick={onInvite}><Plus size={14} /> Invite user</Button>}
      />

      <Surface border="soft" shadow="none" className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b-[2px] border-ink-black/10 bg-bristol px-4 py-4 md:px-5">
          <div className="relative min-w-[260px] flex-1 md:max-w-md">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-soft" />
            <input aria-label="Search users" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search by name, email, or ID" className="h-11 w-full border-[2px] border-ink-black/18 bg-pulp-paper pl-9 pr-3 font-body text-[0.78rem] text-ink-black outline-none placeholder:text-ink-soft hover:border-ink-black/40 focus:border-hero-red focus:bg-bristol" />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5 font-meta text-[0.54rem] font-bold uppercase tracking-[0.12em] text-ink-muted"><Filter size={13} /> Filter</div>
            {(["all", "active", "attention", "trial"] as UserFilter[]).map((option) => (
              <button key={option} type="button" onClick={() => setFilter(option)} className={cn("min-h-9 px-3 font-meta text-[0.56rem] font-bold uppercase tracking-[0.1em] transition-colors", filter === option ? "bg-ink-black text-bristol" : "bg-surface-container text-ink-muted hover:bg-narrator-gold hover:text-ink-black")}>
                {option === "all" ? "All users" : option === "attention" ? "Needs attention" : option}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 bg-surface-container px-5 py-3">
          <div className="font-body text-[0.72rem] font-semibold text-ink-muted"><span className="font-bold text-ink-black">{filteredUsers.length}</span> of {users.length} accounts</div>
          <div className="flex items-center gap-4 font-meta text-[0.52rem] font-bold uppercase tracking-[0.11em] text-ink-muted"><span><span className="text-archive-sage">●</span> {users.filter((user) => user.status === "active").length} active</span><span><span className="text-hero-red">●</span> {users.filter((user) => user.status === "past_due").length} billing holds</span></div>
        </div>

        <div role="region" tabIndex={0} aria-label="Users table; scroll horizontally to see all columns" className="overflow-x-auto">
          <table className="w-full min-w-[920px] text-left">
            <thead className="border-b-[2px] border-ink-black/12 font-meta text-[0.52rem] font-bold uppercase tracking-[0.14em] text-ink-muted">
              <tr><th className="px-5 py-3">User</th><th className="px-3 py-3">Plan</th><th className="px-3 py-3">Projects</th><th className="px-3 py-3">Current work</th><th className="px-3 py-3">Credits</th><th className="px-3 py-3">Last seen</th><th className="px-5 py-3 text-right">State</th></tr>
            </thead>
            <tbody className="divide-y-[2px] divide-ink-black/8">
              {filteredUsers.map((user) => (
                <tr key={user.id} className="group transition-colors hover:bg-surface-container/75">
                  <td className="px-5 py-4"><button type="button" onClick={() => onOpenUser(user.id)} className="flex items-center gap-3 text-left"><Avatar user={user} size="md" /><span className="min-w-0"><span className="block font-body text-[0.78rem] font-bold text-ink-black underline decoration-transparent decoration-2 underline-offset-4 transition-colors group-hover:decoration-hero-red">{user.name}</span><span className="mt-1 block truncate font-body text-[0.67rem] text-ink-soft">{user.email}</span></span></button></td>
                  <td className="px-3 py-4"><span className="font-meta text-[0.58rem] font-bold uppercase tracking-[0.1em] text-ink-black">{user.plan}</span></td>
                  <td className="px-3 py-4 font-meta text-[0.64rem] font-bold tabular-nums text-ink-black">{user.projects}</td>
                  <td className="max-w-[190px] px-3 py-4 font-body text-[0.7rem] font-semibold text-ink-muted">{user.currentStage}</td>
                  <td className="px-3 py-4 font-meta text-[0.68rem] font-bold tabular-nums text-ink-black">{user.credits.toLocaleString()}</td>
                  <td className="px-3 py-4 font-body text-[0.68rem] font-semibold text-ink-soft">{user.lastSeen}</td>
                  <td className="px-5 py-4 text-right"><StateTag label={USER_STATUS[user.status].label} tone={USER_STATUS[user.status].tone} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {filteredUsers.length === 0 && <div className="px-5 py-16 text-center"><div className="mx-auto flex h-12 w-12 items-center justify-center border-[2px] border-ink-black bg-narrator-gold"><Search size={19} /></div><h2 className="mt-4 font-display text-[1.25rem] font-black">No accounts found</h2><p className="mt-2 font-body text-[0.78rem] text-ink-muted">Try a different name, email, or filter.</p></div>}
        </div>
      </Surface>

      <div className="mt-5 grid gap-5 md:grid-cols-3">
        <Surface border="soft" shadow="none" tone="container" padding="md"><div className="flex items-start gap-3"><UserCheck className="mt-0.5" size={17} /><div><div className="font-meta text-[0.54rem] font-bold uppercase tracking-[0.13em] text-ink-muted">Account health</div><div className="mt-2 font-display text-[1.5rem] font-black">94.8%</div><p className="mt-1 font-body text-[0.68rem] text-ink-soft">Accounts with no unresolved risk signal.</p></div></div></Surface>
        <Surface border="soft" shadow="none" tone="container" padding="md"><div className="flex items-start gap-3"><CreditCard className="mt-0.5" size={17} /><div><div className="font-meta text-[0.54rem] font-bold uppercase tracking-[0.13em] text-ink-muted">Credit balance</div><div className="mt-2 font-display text-[1.5rem] font-black">184.2k</div><p className="mt-1 font-body text-[0.68rem] text-ink-soft">Credits held across active accounts.</p></div></div></Surface>
        <Surface border="soft" shadow="none" tone="container" padding="md"><div className="flex items-start gap-3"><MessageCircle className="mt-0.5" size={17} /><div><div className="font-meta text-[0.54rem] font-bold uppercase tracking-[0.13em] text-ink-muted">Median response</div><div className="mt-2 font-display text-[1.5rem] font-black">12m</div><p className="mt-1 font-body text-[0.68rem] text-ink-soft">Across the last 30 resolved threads.</p></div></div></Surface>
      </div>
    </>
  );
}

function UserDrawer({
  user,
  onClose,
  onGrantCredits,
  onToggleSuspension,
  onAction,
}: {
  user: BackofficeUser;
  onClose: () => void;
  onGrantCredits: (userId: string, amount: number) => void;
  onToggleSuspension: (userId: string) => void;
  onAction: (message: string) => void;
}) {
  const [note, setNote] = useState("");

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  function saveNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!note.trim()) return;
    onAction(`Internal note saved for ${user.name}.`);
    setNote("");
  }

  return (
    <>
      <button type="button" aria-label="Close user details" onClick={onClose} className="fixed inset-0 z-[60] cursor-default bg-ink-black/40" />
      <aside aria-label={`${user.name} account details`} className="fixed inset-y-0 right-0 z-[70] flex w-full max-w-[450px] flex-col border-l-[2px] border-ink-black bg-pulp-paper shadow-[-8px_0_0_0_var(--color-ghost-shadow)]">
        <div className="flex items-center justify-between border-b-[2px] border-ink-black bg-bristol px-5 py-4">
          <div className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.15em] text-ink-muted">Account record</div>
          <button type="button" onClick={onClose} aria-label="Close account record" className="flex h-9 w-9 items-center justify-center border-[2px] border-ink-black/18 bg-pulp-paper text-ink-black hover:border-ink-black hover:bg-surface-container"><X size={15} /></button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="border-b-[2px] border-ink-black bg-bristol px-5 py-6">
            <div className="flex items-start gap-4"><Avatar user={user} size="lg" /><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h2 className="font-display text-[1.65rem] font-black leading-none tracking-[-0.04em]">{user.name}</h2><StateTag label={USER_STATUS[user.status].label} tone={USER_STATUS[user.status].tone} /></div><p className="mt-2 truncate font-body text-[0.76rem] text-ink-muted">{user.email}</p><p className="mt-1 font-meta text-[0.52rem] uppercase tracking-[0.12em] text-ink-soft">Joined {user.joined} · {user.location}</p></div></div>
            <div className="mt-5 flex flex-wrap gap-2">{user.tags.map((tag) => <span key={tag} className="bg-surface-container px-2 py-1 font-meta text-[0.52rem] font-bold uppercase tracking-[0.1em] text-ink-muted">{tag}</span>)}</div>
          </div>

          <div className="grid grid-cols-2 border-b-[2px] border-ink-black/10 bg-surface-container"><div className="border-r-[2px] border-ink-black/10 px-5 py-4"><div className="font-meta text-[0.52rem] uppercase tracking-[0.12em] text-ink-muted">Credits available</div><div className="mt-2 font-display text-[1.65rem] font-black tabular-nums">{user.credits.toLocaleString()}</div><div className="mt-1 font-body text-[0.65rem] text-ink-soft">{user.plan} plan</div></div><div className="px-5 py-4"><div className="font-meta text-[0.52rem] uppercase tracking-[0.12em] text-ink-muted">Lifetime spend</div><div className="mt-2 font-display text-[1.65rem] font-black tabular-nums">{formatMoney(user.spend)}</div><div className="mt-1 font-body text-[0.65rem] text-ink-soft">{user.projects} projects</div></div></div>

          <section className="border-b-[2px] border-ink-black/10 px-5 py-5"><div className="font-meta text-[0.54rem] font-bold uppercase tracking-[0.14em] text-ink-muted">Latest signal</div><div className="mt-3 flex gap-3"><span className="mt-1 h-2.5 w-2.5 shrink-0 bg-hero-red" /><div><p className="font-body text-[0.8rem] font-bold">{user.lastEvent}</p><p className="mt-1 font-body text-[0.7rem] leading-5 text-ink-soft">Last seen {user.lastSeen}. Current work: {user.currentStage}.</p></div></div></section>

          <section className="border-b-[2px] border-ink-black/10 px-5 py-5"><div className="font-meta text-[0.54rem] font-bold uppercase tracking-[0.14em] text-ink-muted">Support actions</div><div className="mt-3 grid gap-2"><Button variant="secondary" size="sm" fullWidth onClick={() => onGrantCredits(user.id, 250)}><Plus size={14} /> Grant 250 credits</Button><Button variant="outline" size="sm" fullWidth onClick={() => onAction(`Password reset email sent to ${user.email}.`)}><LockKeyhole size={14} /> Send password reset</Button><Button variant="outline" size="sm" fullWidth className={user.status === "suspended" ? "border-archive-sage text-archive-sage hover:bg-chip-sage" : "border-hero-red text-hero-red hover:bg-chip-red"} onClick={() => onToggleSuspension(user.id)}>{user.status === "suspended" ? <><UserCheck size={14} /> Restore account</> : <><ShieldAlert size={14} /> Suspend account</>}</Button></div></section>

          <section className="px-5 py-5"><div className="flex items-center justify-between gap-3"><div className="font-meta text-[0.54rem] font-bold uppercase tracking-[0.14em] text-ink-muted">Operator notes</div><span className="font-meta text-[0.5rem] uppercase tracking-[0.1em] text-ink-soft">local only</span></div><form onSubmit={saveNote} className="mt-3"><textarea value={note} onChange={(event) => setNote(event.target.value)} rows={4} placeholder="Add context for the next shift…" className="w-full resize-y border-[2px] border-ink-black/18 bg-bristol px-3 py-2.5 font-body text-[0.76rem] leading-5 text-ink-black outline-none placeholder:text-ink-soft hover:border-ink-black/40 focus:border-hero-red" /><div className="mt-2 flex justify-end"><Button size="xs" type="submit" disabled={!note.trim()}>Save note</Button></div></form></section>
        </div>
        <div className="border-t-[2px] border-ink-black bg-ink-black px-5 py-3"><div className="flex items-center justify-between gap-3"><span className="font-meta text-[0.52rem] uppercase tracking-[0.12em] text-bristol/60">Customer view</span><Link to="/" onClick={onClose} className="inline-flex items-center gap-2 font-meta text-[0.56rem] font-bold uppercase tracking-[0.1em] text-bristol hover:text-narrator-gold">Open Scenewright <ExternalLink size={12} /></Link></div></div>
      </aside>
    </>
  );
}

function SupportView({
  tickets,
  users,
  selectedTicketId,
  onSelectTicket,
  onResolve,
  onSendReply,
}: {
  tickets: SupportTicket[];
  users: BackofficeUser[];
  selectedTicketId: string;
  onSelectTicket: (ticketId: string) => void;
  onResolve: (ticketId: string) => void;
  onSendReply: (ticketId: string, body: string) => void;
}) {
  const [reply, setReply] = useState("");
  const activeTicket = tickets.find((ticket) => ticket.id === selectedTicketId) ?? tickets[0];
  const activeTickets = tickets.filter((ticket) => ticket.status !== "resolved");
  const userById = (userId: string) => users.find((user) => user.id === userId);

  function submitReply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeTicket || !reply.trim()) return;
    onSendReply(activeTicket.id, reply.trim());
    setReply("");
  }

  return (
    <>
      <PageHeading view="support" actions={<Button variant="outline" size="sm"><Settings2 size={14} /> Queue settings</Button>} />
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4"><Surface border="soft" shadow="none" tone="container" padding="sm"><div className="font-meta text-[0.52rem] uppercase tracking-[0.12em] text-ink-muted">Open</div><div className="mt-2 font-display text-[1.6rem] font-black">{activeTickets.length}</div></Surface><Surface border="soft" shadow="none" tone="container" padding="sm"><div className="font-meta text-[0.52rem] uppercase tracking-[0.12em] text-ink-muted">Urgent</div><div className="mt-2 font-display text-[1.6rem] font-black text-hero-red">{activeTickets.filter((ticket) => ticket.priority === "urgent").length}</div></Surface><Surface border="soft" shadow="none" tone="container" padding="sm"><div className="font-meta text-[0.52rem] uppercase tracking-[0.12em] text-ink-muted">Avg. first reply</div><div className="mt-2 font-display text-[1.6rem] font-black">12m</div></Surface><Surface border="soft" shadow="none" tone="container" padding="sm"><div className="font-meta text-[0.52rem] uppercase tracking-[0.12em] text-ink-muted">Resolved today</div><div className="mt-2 font-display text-[1.6rem] font-black text-archive-sage">14</div></Surface></div>

      <div className="grid min-h-[610px] gap-5 xl:grid-cols-[minmax(300px,0.72fr)_minmax(0,1.45fr)]">
        <Surface border="soft" shadow="none" className="min-w-0 overflow-hidden">
          <div className="flex items-center justify-between gap-3 border-b-[2px] border-ink-black/10 px-5 py-4"><div><div className="font-meta text-[0.54rem] font-bold uppercase tracking-[0.14em] text-ink-muted">Inbox</div><h2 className="mt-1 font-display text-[1.2rem] font-black leading-none">All conversations</h2></div><button type="button" aria-label="Filter support queue" className="flex h-9 w-9 items-center justify-center border-[2px] border-ink-black/18 bg-pulp-paper hover:border-ink-black"><Filter size={14} /></button></div>
          <div className="flex border-b-[2px] border-ink-black/10 bg-surface-container px-3 py-2"><span className="bg-ink-black px-2 py-1 font-meta text-[0.5rem] font-bold uppercase tracking-[0.1em] text-bristol">All {tickets.length}</span><span className="px-2 py-1 font-meta text-[0.5rem] font-bold uppercase tracking-[0.1em] text-ink-soft">Unassigned {activeTickets.length}</span></div>
          <div className="max-h-[calc(100vh-300px)] overflow-y-auto">
            {tickets.map((ticket) => { const user = userById(ticket.userId); const selected = ticket.id === activeTicket?.id; return <button key={ticket.id} type="button" onClick={() => onSelectTicket(ticket.id)} className={cn("flex w-full gap-3 border-b-[2px] border-ink-black/8 px-4 py-4 text-left transition-colors", selected ? "bg-chip-red" : "hover:bg-surface-container")}><span className={cn("mt-1 h-2.5 w-2.5 shrink-0 border-[2px] border-ink-black", ticket.priority === "urgent" ? "bg-hero-red" : ticket.status === "resolved" ? "bg-archive-sage" : "bg-narrator-gold")} /><span className="min-w-0 flex-1"><span className="flex items-baseline justify-between gap-2"><span className="truncate font-body text-[0.74rem] font-bold text-ink-black">{ticket.subject}</span><span className="shrink-0 font-meta text-[0.48rem] uppercase tracking-[0.08em] text-ink-soft">{ticket.updated}</span></span><span className="mt-1 block truncate font-body text-[0.66rem] text-ink-muted">{user?.name} · {ticket.id}</span><span className="mt-2 flex items-center gap-2"><StateTag label={TICKET_STATUS[ticket.status].label} tone={TICKET_STATUS[ticket.status].tone} /><span className="font-meta text-[0.48rem] uppercase tracking-[0.08em] text-ink-soft">{ticket.category}</span></span></span></button>; })}
          </div>
        </Surface>

        {activeTicket && (
          <Surface border="soft" shadow="none" className="flex min-w-0 flex-col overflow-hidden">
            <div className="flex flex-wrap items-start justify-between gap-4 border-b-[2px] border-ink-black/10 bg-bristol px-5 py-4"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><StateTag label={PRIORITY_META[activeTicket.priority].label} tone={PRIORITY_META[activeTicket.priority].tone} /><span className="font-meta text-[0.52rem] font-bold uppercase tracking-[0.1em] text-ink-soft">{activeTicket.id}</span></div><h2 className="mt-2 font-display text-[1.55rem] font-black leading-[1.02] tracking-[-0.035em]">{activeTicket.subject}</h2><div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-body text-[0.68rem] text-ink-soft"><span>{userById(activeTicket.userId)?.name}</span><span>·</span><span>{userById(activeTicket.userId)?.email}</span></div></div><div className="flex items-center gap-2"><button type="button" aria-label="More ticket actions" className="flex h-9 w-9 items-center justify-center border-[2px] border-ink-black/18 bg-pulp-paper hover:border-ink-black"><MoreHorizontal size={15} /></button>{activeTicket.status !== "resolved" && <Button size="xs" onClick={() => onResolve(activeTicket.id)}><Check size={13} /> Resolve</Button>}</div></div>
            <div className="flex-1 space-y-4 overflow-y-auto bg-surface-container/60 px-5 py-5">
              <div className="flex items-center gap-3 font-meta text-[0.5rem] font-bold uppercase tracking-[0.12em] text-ink-soft"><span className="h-[2px] flex-1 bg-ink-black/10" /> Conversation <span className="h-[2px] flex-1 bg-ink-black/10" /></div>
              {activeTicket.messages.map((message) => { const user = userById(activeTicket.userId); const operator = message.author === "operator"; return <div key={message.id} className={cn("flex gap-3", operator ? "justify-end" : "justify-start")}><div className={cn("max-w-[min(78%,560px)]", operator ? "items-end" : "items-start")}><div className={cn("flex items-center gap-2", operator && "justify-end")}><span className="font-meta text-[0.5rem] font-bold uppercase tracking-[0.11em] text-ink-muted">{operator ? "Operator desk" : user?.name}</span><time className="font-meta text-[0.48rem] uppercase tracking-[0.08em] text-ink-soft">{message.timestamp}</time></div><div className={cn("mt-1.5 border-[2px] border-ink-black px-3.5 py-3 font-body text-[0.77rem] leading-5", operator ? "bg-ink-black text-bristol" : "bg-bristol text-ink-black shadow-paper-sm")}>{message.body}</div></div></div>; })}
              {activeTicket.status === "resolved" && <div className="flex items-center justify-center gap-2 border-[2px] border-archive-sage bg-chip-sage px-3 py-2 font-meta text-[0.54rem] font-bold uppercase tracking-[0.1em] text-ink-black"><CircleCheck size={13} /> Resolved and archived</div>}
            </div>
            <form onSubmit={submitReply} className="border-t-[2px] border-ink-black bg-bristol p-4"><div className="flex items-end gap-2"><textarea aria-label="Reply to customer" value={reply} onChange={(event) => setReply(event.target.value)} rows={3} placeholder="Write a clear, specific reply…" disabled={activeTicket.status === "resolved"} className="min-h-[80px] flex-1 resize-none border-[2px] border-ink-black/18 bg-pulp-paper px-3 py-2.5 font-body text-[0.76rem] leading-5 outline-none placeholder:text-ink-soft hover:border-ink-black/40 focus:border-hero-red disabled:cursor-not-allowed disabled:opacity-55" /><Button type="submit" size="sm" disabled={!reply.trim() || activeTicket.status === "resolved"}><Send size={14} /> Send</Button></div><div className="mt-2 flex items-center justify-between gap-3 font-meta text-[0.5rem] uppercase tracking-[0.1em] text-ink-soft"><span>Replies are staged in this local workspace.</span><span>{reply.length}/1000</span></div></form>
          </Surface>
        )}
      </div>
    </>
  );
}

function AnalyticsView({ onExport }: { onExport: () => void }) {
  return (
    <>
      <PageHeading view="analytics" actions={<Button variant="outline" size="sm" onClick={onExport}><Download size={14} /> Export report</Button>} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4"><MetricCell label="Weekly active" value="712" detail="unique creators" delta="8.2%" /><MetricCell label="Projects started" value="186" detail="this week" delta="15.1%" /><MetricCell label="Book exports" value="43" detail="last 7 days" delta="6.4%" /><MetricCell label="Provider spend" value="$342" detail="this week" delta="3.1%" deltaTone="down" /></div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(330px,0.75fr)]">
        <Surface border="soft" shadow="none" className="min-w-0 overflow-hidden"><PanelHeading kicker="90-day view" title="Usage and conversion" detail="Active creators against the share that reaches a finished book." /><UsageChart points={ANALYTICS_SERIES} /><div className="grid grid-cols-3 border-t-[2px] border-ink-black/10 bg-surface-container"><div className="px-4 py-3"><div className="font-meta text-[0.5rem] uppercase tracking-[0.12em] text-ink-muted">Activation</div><div className="mt-1 font-display text-[1.25rem] font-black">56%</div></div><div className="border-l-[2px] border-ink-black/10 px-4 py-3"><div className="font-meta text-[0.5rem] uppercase tracking-[0.12em] text-ink-muted">Project → book</div><div className="mt-1 font-display text-[1.25rem] font-black">22%</div></div><div className="border-l-[2px] border-ink-black/10 px-4 py-3"><div className="font-meta text-[0.5rem] uppercase tracking-[0.12em] text-ink-muted">Median time</div><div className="mt-1 font-display text-[1.25rem] font-black">2.8d</div></div></div></Surface>

        <Surface border="soft" shadow="none" className="overflow-hidden"><PanelHeading kicker="Creator journey" title="Funnel" detail="Where a new account pauses on the way to an export." /><div className="space-y-5 px-5 py-6">{FUNNEL_STEPS.map((step, index) => <div key={step.label}><div className="flex items-baseline justify-between gap-3"><span className="font-body text-[0.74rem] font-bold">{step.label}</span><span className="font-meta text-[0.62rem] font-bold tabular-nums text-ink-muted">{step.value.toLocaleString()} <span className="text-ink-soft">· {step.percent}%</span></span></div><div className="mt-2 h-3 bg-surface-container"><div className={cn("h-full", index === FUNNEL_STEPS.length - 1 ? "bg-hero-red" : index === 0 ? "bg-ink-black" : "bg-narrator-gold")} style={{ width: `${step.percent}%` }} /></div></div>)}</div><div className="border-t-[2px] border-ink-black/10 bg-chip-gold px-5 py-3 font-body text-[0.7rem] font-semibold text-ink-black">The largest pause is between choosing a look and starting the press run.</div></Surface>
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(330px,0.85fr)]">
        <Surface border="soft" shadow="none" className="overflow-hidden"><PanelHeading kicker="Cost watch" title="Model spend" detail="Provider costs are aggregate in this local view; customer IDs stay out of analytics." action={<span className="font-meta text-[0.52rem] font-bold uppercase tracking-[0.1em] text-archive-sage">On budget</span>} /><div role="region" tabIndex={0} aria-label="Model spend table; scroll horizontally to see all columns" className="overflow-x-auto"><table className="w-full min-w-[640px] text-left"><thead className="bg-surface-container font-meta text-[0.5rem] font-bold uppercase tracking-[0.12em] text-ink-muted"><tr><th className="px-5 py-3">Model route</th><th className="px-3 py-3">Calls</th><th className="px-3 py-3">Share</th><th className="px-5 py-3 text-right">Spend</th></tr></thead><tbody className="divide-y-[2px] divide-ink-black/8">{MODEL_SPEND.map((row) => <tr key={row.alias} className="hover:bg-surface-container/70"><td className="px-5 py-4"><div className="flex items-center gap-3"><span className={cn("h-3 w-3 border-[2px] border-ink-black", row.tone === "red" ? "bg-hero-red" : row.tone === "gold" ? "bg-narrator-gold" : row.tone === "blue" ? "bg-secondary-container" : "bg-archive-sage")} /><div><div className="font-body text-[0.74rem] font-bold">{row.model}</div><div className="mt-0.5 font-meta text-[0.5rem] uppercase tracking-[0.1em] text-ink-soft">{row.alias}</div></div></div></td><td className="px-3 py-4 font-meta text-[0.64rem] font-bold tabular-nums">{row.calls.toLocaleString()}</td><td className="px-3 py-4"><div className="flex items-center gap-2"><div className="h-2 w-16 bg-surface-container"><div className="h-full bg-ink-black" style={{ width: `${row.share}%` }} /></div><span className="font-meta text-[0.58rem] font-bold tabular-nums text-ink-muted">{row.share}%</span></div></td><td className="px-5 py-4 text-right font-meta text-[0.66rem] font-bold tabular-nums">{formatMoney(row.spend)}</td></tr>)}</tbody></table></div></Surface>

        <Surface border="soft" shadow="none" className="overflow-hidden"><PanelHeading kicker="Signals" title="What to watch" /><div className="space-y-1 px-5 py-3"><div className="flex gap-3 py-3"><span className="mt-1 h-2.5 w-2.5 shrink-0 bg-hero-red" /><div><div className="font-body text-[0.75rem] font-bold">Billing retries are up</div><p className="mt-1 font-body text-[0.68rem] leading-5 text-ink-soft">Past-due accounts rose 2.1% after the latest checkout change.</p></div></div><div className="flex gap-3 py-3"><span className="mt-1 h-2.5 w-2.5 shrink-0 bg-narrator-gold" /><div><div className="font-body text-[0.75rem] font-bold">Style approval is the hinge</div><p className="mt-1 font-body text-[0.68rem] leading-5 text-ink-soft">Creators who choose a look within 24 hours are 3.4× more likely to export.</p></div></div><div className="flex gap-3 py-3"><span className="mt-1 h-2.5 w-2.5 shrink-0 bg-archive-sage" /><div><div className="font-body text-[0.75rem] font-bold">Image balance is holding</div><p className="mt-1 font-body text-[0.68rem] leading-5 text-ink-soft">Balanced routing remains inside the $0.42 per-page target.</p></div></div></div><div className="border-t-[2px] border-ink-black/10 bg-surface-container px-5 py-4"><div className="flex items-center gap-2 font-meta text-[0.54rem] font-bold uppercase tracking-[0.1em] text-ink-muted"><Gauge size={14} /> Last reconciled 8 min ago</div></div></Surface>
      </div>
    </>
  );
}

function BackofficeSidebar({
  activeView,
  open,
  onNavigate,
  onClose,
}: {
  activeView: BackofficeView;
  open: boolean;
  onNavigate: (view: BackofficeView) => void;
  onClose: () => void;
}) {
  return (
    <>
      {open && <button type="button" aria-label="Close navigation" onClick={onClose} className="fixed inset-0 z-[65] bg-ink-black/45 lg:hidden" />}
      <aside className={cn("backoffice-sidebar z-[70] flex h-dvh w-[252px] shrink-0 flex-col bg-ink-black text-bristol", open ? "fixed inset-y-0 left-0" : "hidden lg:sticky lg:top-0 lg:flex")}>
        <div className="border-b-[2px] border-bristol/12 px-5 py-5"><div className="flex items-center gap-3"><BrandMark className="h-9 w-9 shrink-0" variant="reversed" /><div><div className="font-display text-[1.15rem] font-black uppercase leading-none tracking-[-0.035em]">Scenewright</div><div className="mt-1 font-meta text-[0.5rem] font-bold uppercase tracking-[0.17em] text-bristol/58">Operator desk</div></div></div></div>
        <div className="mx-4 mt-5 border-[2px] border-bristol/16 bg-bristol/6 px-3 py-3"><div className="flex items-center gap-2 font-meta text-[0.52rem] font-bold uppercase tracking-[0.12em] text-narrator-gold"><span className="h-2 w-2 bg-narrator-gold" /> Local workspace</div><p className="mt-2 font-body text-[0.67rem] leading-5 text-bristol/62">Seeded operator data · changes stay in this tab.</p></div>
        <nav aria-label="Backoffice sections" className="min-h-0 flex-1 px-3 py-6"><div className="mb-2 px-3 font-meta text-[0.5rem] font-bold uppercase tracking-[0.16em] text-bristol/38">Control room</div>{NAV_ITEMS.map(({ key, label, icon: Icon, shortcut }) => { const selected = key === activeView; return <button key={key} type="button" onClick={() => { onNavigate(key); onClose(); }} aria-current={selected ? "page" : undefined} className={cn("group flex min-h-12 w-full items-center gap-3 px-3 text-left transition-colors", selected ? "bg-bristol text-ink-black shadow-[4px_4px_0_0_var(--color-hero-red)]" : "text-bristol/72 hover:bg-bristol/8 hover:text-bristol")}><Icon size={16} strokeWidth={selected ? 2 : 1.6} /><span className="font-body text-[0.78rem] font-bold">{label}</span><span className={cn("ml-auto font-meta text-[0.5rem] tracking-[0.08em]", selected ? "text-ink-soft" : "text-bristol/32")}>{shortcut}</span></button>; })}</nav>
        <div className="border-t-[2px] border-bristol/12 px-4 py-4"><div className="flex items-center gap-2 font-meta text-[0.52rem] font-bold uppercase tracking-[0.11em] text-bristol/72"><span className="h-2 w-2 bg-archive-sage" /> All systems nominal</div><div className="mt-4 flex items-center justify-between gap-3"><Link to="/" className="font-meta text-[0.55rem] font-bold uppercase tracking-[0.1em] text-bristol/55 hover:text-narrator-gold">← Scenewright</Link><span className="font-meta text-[0.48rem] uppercase tracking-[0.1em] text-bristol/32">v0.1 local</span></div></div>
      </aside>
    </>
  );
}

function BackofficeHeader({
  activeView,
  range,
  onOpenMenu,
  onRefresh,
  onRangeChange,
}: {
  activeView: BackofficeView;
  range: RangeKey;
  onOpenMenu: () => void;
  onRefresh: () => void;
  onRangeChange: (range: RangeKey) => void;
}) {
  return (
    <header className="sticky top-0 z-40 border-b-[2px] border-ink-black/12 bg-pulp-paper">
      <div className="flex min-h-[72px] items-center justify-between gap-4 px-4 md:px-6 xl:px-9"><div className="flex min-w-0 items-center gap-3"><button type="button" onClick={onOpenMenu} aria-label="Open navigation" className="flex h-10 w-10 shrink-0 items-center justify-center border-[2px] border-ink-black bg-bristol lg:hidden"><Menu size={17} /></button><div className="min-w-0"><div className="flex items-center gap-2 font-meta text-[0.52rem] font-bold uppercase tracking-[0.14em] text-ink-soft"><span>Operator desk</span><span>/</span><span className="text-hero-red">{VIEW_META[activeView].title}</span></div><div className="mt-1 truncate font-display text-[1.15rem] font-black leading-none tracking-[-0.03em] text-ink-black">{activeView === "overview" ? "Overview" : VIEW_META[activeView].title}</div></div></div><div className="flex shrink-0 items-center gap-2 md:gap-3"><select aria-label="Analytics date range" value={range} onChange={(event) => onRangeChange(event.target.value as RangeKey)} className="hidden h-10 border-[2px] border-ink-black/18 bg-bristol px-2.5 font-meta text-[0.56rem] font-bold uppercase tracking-[0.1em] text-ink-black outline-none hover:border-ink-black focus:border-hero-red sm:block"><option value="7d">7 days</option><option value="30d">30 days</option><option value="90d">90 days</option></select><div className="hidden items-center gap-2 border-[2px] border-archive-sage bg-chip-sage px-3 py-2 font-meta text-[0.52rem] font-bold uppercase tracking-[0.1em] text-ink-black md:flex"><span className="h-2 w-2 bg-archive-sage" /> Live</div><button type="button" onClick={onRefresh} aria-label="Refresh data" className="flex h-10 w-10 items-center justify-center border-[2px] border-ink-black/18 bg-bristol hover:border-ink-black hover:bg-surface-container"><RefreshCw size={14} /></button><div className="flex h-10 w-10 items-center justify-center border-[2px] border-ink-black bg-hero-red font-meta text-[0.6rem] font-bold tracking-[0.06em] text-bristol">JB</div></div></div>
    </header>
  );
}

export function BackofficePage() {
  const [activeView, setActiveView] = useState<BackofficeView>("overview");
  const [range, setRange] = useState<RangeKey>("30d");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [selectedTicketId, setSelectedTicketId] = useState(BACKOFFICE_TICKETS[0]?.id ?? "");
  const [users, setUsers] = useState<BackofficeUser[]>(BACKOFFICE_USERS);
  const [tickets, setTickets] = useState<SupportTicket[]>(BACKOFFICE_TICKETS);
  const [notice, setNotice] = useState<{ message: string; tone: NoticeTone } | null>(null);

  const selectedUser = users.find((user) => user.id === selectedUserId) ?? null;

  useEffect(() => {
    if (!notice) return;
    const timeout = window.setTimeout(() => setNotice(null), 3600);
    return () => window.clearTimeout(timeout);
  }, [notice]);

  function showNotice(message: string, tone: NoticeTone = "ink") {
    setNotice({ message, tone });
  }

  function refresh() {
    showNotice("Local operator data refreshed.", "sage");
  }

  function grantCredits(userId: string, amount: number) {
    setUsers((current) => current.map((user) => user.id === userId ? { ...user, credits: user.credits + amount } : user));
    const user = users.find((candidate) => candidate.id === userId);
    showNotice(`${amount.toLocaleString()} credits staged for ${user?.name ?? "this account"}.`, "gold");
  }

  function toggleSuspension(userId: string) {
    setUsers((current) => current.map((user) => user.id === userId ? { ...user, status: user.status === "suspended" ? "active" : "suspended" } : user));
    const user = users.find((candidate) => candidate.id === userId);
    showNotice(`${user?.name ?? "Account"} is now ${user?.status === "suspended" ? "active" : "suspended"}.`, user?.status === "suspended" ? "sage" : "red");
  }

  function resolveTicket(ticketId: string) {
    setTickets((current) => current.map((ticket) => ticket.id === ticketId ? { ...ticket, status: "resolved", updated: "just now" } : ticket));
    showNotice(`${ticketId} marked resolved.`, "sage");
  }

  function sendReply(ticketId: string, body: string) {
    setTickets((current) => current.map((ticket) => ticket.id === ticketId ? { ...ticket, status: "waiting", updated: "just now", messages: [...ticket.messages, { id: `msg_${Date.now()}`, author: "operator", body, timestamp: "Just now" }] } : ticket));
    showNotice("Reply staged in the local workspace.", "blue");
  }

  function exportReport() {
    const lines = [
      ["metric", "value"],
      ["weekly_active_creators", "712"],
      ["projects_started", "186"],
      ["book_exports", "43"],
      ["provider_spend_usd", "342"],
      ...MODEL_SPEND.map((row) => [`model_spend_${row.alias}`, row.spend.toFixed(2)]),
    ].map((row) => row.join(","));
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "scenewright-operator-report.csv";
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    showNotice("Analytics report downloaded.", "sage");
  }

  function navigate(view: BackofficeView) {
    setActiveView(view);
    if (view !== "users") setSelectedUserId(null);
  }

  return (
    <div className="backoffice-root flex min-h-dvh bg-surface-container text-ink-black">
      <a href="#backoffice-content" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:bg-hero-red focus:px-4 focus:py-2 focus:font-meta focus:text-[0.6rem] focus:font-bold focus:uppercase focus:tracking-[0.12em] focus:text-bristol">Skip to content</a>
      <BackofficeSidebar activeView={activeView} open={mobileNavOpen} onNavigate={navigate} onClose={() => setMobileNavOpen(false)} />
      <div className="flex min-h-dvh min-w-0 flex-1 flex-col lg:ml-0">
        <BackofficeHeader activeView={activeView} range={range} onOpenMenu={() => setMobileNavOpen(true)} onRefresh={refresh} onRangeChange={setRange} />
        <main id="backoffice-content" className="backoffice-main flex-1 px-4 py-6 md:px-6 md:py-8 xl:px-9 xl:py-10">
          <div className="mx-auto w-full max-w-[1480px] backoffice-enter">
            {activeView === "overview" && <OverviewView range={range} onRangeChange={setRange} onViewChange={navigate} onRefresh={refresh} users={users} tickets={tickets} />}
            {activeView === "users" && <UsersView users={users} onOpenUser={setSelectedUserId} onInvite={() => showNotice("Invite flow is ready for an operator API.", "blue")} />}
            {activeView === "support" && <SupportView tickets={tickets} users={users} selectedTicketId={selectedTicketId} onSelectTicket={setSelectedTicketId} onResolve={resolveTicket} onSendReply={sendReply} />}
            {activeView === "analytics" && <AnalyticsView onExport={exportReport} />}
          </div>
        </main>
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t-[2px] border-ink-black/10 bg-pulp-paper px-4 py-4 font-meta text-[0.5rem] font-bold uppercase tracking-[0.12em] text-ink-soft md:px-6 xl:px-9"><span>Local operator workspace · seeded data</span><span className="flex items-center gap-2"><span className="h-2 w-2 bg-archive-sage" /> No external writes</span></footer>
      </div>

      {selectedUser && <UserDrawer user={selectedUser} onClose={() => setSelectedUserId(null)} onGrantCredits={grantCredits} onToggleSuspension={toggleSuspension} onAction={(message) => showNotice(message, "blue")} />}
      {notice && <div role="status" aria-live="polite" className={cn("backoffice-notice fixed bottom-4 right-4 z-[90] flex max-w-[360px] items-start gap-3 border-[2px] border-ink-black px-4 py-3 shadow-ink-sm", NOTICE_TONE[notice.tone])}><CircleCheck size={16} className="mt-0.5 shrink-0" /><span className="font-body text-[0.74rem] font-bold leading-5">{notice.message}</span><button type="button" aria-label="Dismiss notification" onClick={() => setNotice(null)} className="ml-auto shrink-0 opacity-70 hover:opacity-100"><X size={14} /></button></div>}
    </div>
  );
}
