export type BackofficeView = "overview" | "users" | "support" | "analytics";

export type UserStatus = "active" | "trial" | "past_due" | "suspended" | "unconfirmed";
export type UserFilter = "all" | "active" | "attention" | "trial";
export type TicketPriority = "urgent" | "normal" | "low";
export type TicketStatus = "open" | "waiting" | "resolved";

export interface BackofficeUser {
  id: string;
  name: string;
  email: string;
  initials: string;
  avatarTone: "red" | "gold" | "blue" | "sage" | "ink";
  plan: string;
  status: UserStatus;
  projects: number;
  credits: number;
  lastSeen: string;
  joined: string;
  currentStage: string;
  spend: number;
  location: string;
  timezone: string;
  lastEvent: string;
  tags: string[];
  source?: "live" | "preview";
  errors?: BackofficeError[];
  projectsDetail?: BackofficeProject[];
  activeJobs?: BackofficeJob[];
}

export interface BackofficeError {
  source: string;
  stage: string;
  projectId?: string | null;
  projectName?: string | null;
  status: string;
  message: string;
  errorType?: string;
  occurredAt?: string | null;
}

export interface BackofficeJob {
  id: string;
  label: string;
  kind: string;
  status: "queued" | "running" | "complete" | "failed";
  projectId?: string | null;
  queuedAt?: string | null;
  startedAt?: string | null;
}

export interface BackofficeProject {
  id: string;
  name: string;
  slug: string;
  createdAt?: string | null;
  status: "idle" | "running" | "review" | "ready" | "error" | "stalled" | "complete";
  isActive: boolean;
  currentStage: string;
  errors: BackofficeError[];
  jobs: Array<BackofficeJob & { finishedAt?: string | null; error?: string | null }>;
}

export interface SupportMessage {
  id: string;
  author: "customer" | "operator";
  body: string;
  timestamp: string;
}

export interface SupportTicket {
  id: string;
  userId: string;
  subject: string;
  priority: TicketPriority;
  status: TicketStatus;
  updated: string;
  category: "generation" | "billing" | "export" | "account";
  messages: SupportMessage[];
}

export interface ActivityItem {
  id: string;
  tone: "red" | "gold" | "sage" | "blue" | "ink";
  title: string;
  detail: string;
  time: string;
}

export interface SeriesPoint {
  label: string;
  value: number;
  secondary?: number;
}

export const BACKOFFICE_USERS: BackofficeUser[] = [
  {
    id: "usr_maya_chen",
    name: "Maya Chen",
    email: "maya.chen@example.com",
    initials: "MC",
    avatarTone: "red",
    plan: "Studio",
    status: "active",
    projects: 3,
    credits: 1240,
    lastSeen: "4 min ago",
    joined: "Jul 18, 2026",
    currentStage: "Reviewing pages",
    spend: 64.2,
    location: "Toronto, CA",
    timezone: "Eastern Time",
    lastEvent: "Flagged page 12 for redraw",
    tags: ["high intent", "returning"],
  },
  {
    id: "usr_oliver_grant",
    name: "Oliver Grant",
    email: "oliver.grant@example.com",
    initials: "OG",
    avatarTone: "blue",
    plan: "Starter",
    status: "active",
    projects: 1,
    credits: 486,
    lastSeen: "18 min ago",
    joined: "Jul 27, 2026",
    currentStage: "Choosing a look",
    spend: 18.0,
    location: "Bristol, UK",
    timezone: "Greenwich Mean Time",
    lastEvent: "Selected pulp noir direction",
    tags: ["new project"],
  },
  {
    id: "usr_ines_navarro",
    name: "Inés Navarro",
    email: "ines.navarro@example.com",
    initials: "IN",
    avatarTone: "gold",
    plan: "Trial",
    status: "trial",
    projects: 1,
    credits: 92,
    lastSeen: "41 min ago",
    joined: "Jul 31, 2026",
    currentStage: "Story review",
    spend: 0,
    location: "Valencia, ES",
    timezone: "Central European Time",
    lastEvent: "Opened Story checkpoint",
    tags: ["trial ends in 5d"],
  },
  {
    id: "usr_rowan_brooks",
    name: "Rowan Brooks",
    email: "rowan.brooks@example.com",
    initials: "RB",
    avatarTone: "sage",
    plan: "Starter",
    status: "past_due",
    projects: 2,
    credits: 0,
    lastSeen: "2 hr ago",
    joined: "Jul 11, 2026",
    currentStage: "Waiting for credits",
    spend: 42.0,
    location: "Portland, US",
    timezone: "Pacific Time",
    lastEvent: "Checkout payment failed",
    tags: ["billing", "at risk"],
  },
  {
    id: "usr_amira_diallo",
    name: "Amira Diallo",
    email: "amira.diallo@example.com",
    initials: "AD",
    avatarTone: "ink",
    plan: "Studio",
    status: "active",
    projects: 6,
    credits: 2830,
    lastSeen: "3 hr ago",
    joined: "Jun 23, 2026",
    currentStage: "Exporting edition",
    spend: 131.8,
    location: "Montreal, CA",
    timezone: "Eastern Time",
    lastEvent: "Exported issue 02 as PDF",
    tags: ["power user", "returning"],
  },
  {
    id: "usr_theo_martin",
    name: "Theo Martin",
    email: "theo.martin@example.com",
    initials: "TM",
    avatarTone: "blue",
    plan: "Starter",
    status: "active",
    projects: 1,
    credits: 604,
    lastSeen: "Yesterday",
    joined: "Jul 22, 2026",
    currentStage: "Preparing panels",
    spend: 24.7,
    location: "Lyon, FR",
    timezone: "Central European Time",
    lastEvent: "Cast approved; panel prep started",
    tags: ["new project"],
  },
  {
    id: "usr_sana_park",
    name: "Sana Park",
    email: "sana.park@example.com",
    initials: "SP",
    avatarTone: "red",
    plan: "Trial",
    status: "suspended",
    projects: 0,
    credits: 0,
    lastSeen: "Jul 28",
    joined: "Jul 28, 2026",
    currentStage: "No active project",
    spend: 0,
    location: "Seoul, KR",
    timezone: "Korea Standard Time",
    lastEvent: "Account paused by operator",
    tags: ["manual review"],
  },
  {
    id: "usr_noah_williams",
    name: "Noah Williams",
    email: "noah.williams@example.com",
    initials: "NW",
    avatarTone: "gold",
    plan: "Studio",
    status: "active",
    projects: 4,
    credits: 1725,
    lastSeen: "Jul 30",
    joined: "Jun 14, 2026",
    currentStage: "Reviewing pages",
    spend: 88.4,
    location: "Austin, US",
    timezone: "Central Time",
    lastEvent: "Approved all drawn pages",
    tags: ["returning"],
  },
];

export const BACKOFFICE_TICKETS: SupportTicket[] = [
  {
    id: "SC-1048",
    userId: "usr_maya_chen",
    subject: "My book stopped after the style proof",
    priority: "urgent",
    status: "open",
    updated: "11 min ago",
    category: "generation",
    messages: [
      {
        id: "msg_1048_1",
        author: "customer",
        body: "The style proof looks great, but the next step has been sitting on ‘casting’ for about twenty minutes. Is that expected?",
        timestamp: "10:42 AM",
      },
      {
        id: "msg_1048_2",
        author: "operator",
        body: "I’m checking the project run now. I’ll keep the proof in place while I trace the stalled step.",
        timestamp: "10:48 AM",
      },
    ],
  },
  {
    id: "SC-1046",
    userId: "usr_rowan_brooks",
    subject: "Credits disappeared after a failed run",
    priority: "urgent",
    status: "open",
    updated: "36 min ago",
    category: "billing",
    messages: [
      {
        id: "msg_1046_1",
        author: "customer",
        body: "My card payment failed, but the 500 credits are gone from the balance. Can you put them back?",
        timestamp: "10:17 AM",
      },
    ],
  },
  {
    id: "SC-1041",
    userId: "usr_theo_martin",
    subject: "Can you help me export a CBZ?",
    priority: "normal",
    status: "waiting",
    updated: "1 hr ago",
    category: "export",
    messages: [
      {
        id: "msg_1041_1",
        author: "customer",
        body: "I can see the PDF export, but I need a CBZ for my reader. Did I miss a setting?",
        timestamp: "9:37 AM",
      },
      {
        id: "msg_1041_2",
        author: "operator",
        body: "CBZ is available from Book → Export once the PDF preflight passes. I’ve sent the exact steps to your inbox.",
        timestamp: "9:54 AM",
      },
    ],
  },
  {
    id: "SC-1039",
    userId: "usr_ines_navarro",
    subject: "How do I change the output language?",
    priority: "low",
    status: "open",
    updated: "3 hr ago",
    category: "account",
    messages: [
      {
        id: "msg_1039_1",
        author: "customer",
        body: "I want the dialogue in Spanish but the interface in English. Can I do that separately?",
        timestamp: "8:11 AM",
      },
    ],
  },
  {
    id: "SC-1034",
    userId: "usr_amira_diallo",
    subject: "Issue 02 exported perfectly",
    priority: "low",
    status: "resolved",
    updated: "Yesterday",
    category: "export",
    messages: [
      {
        id: "msg_1034_1",
        author: "customer",
        body: "Just wanted to say the preflight notes were very clear. The CBZ opened on my reader first try.",
        timestamp: "Jul 31",
      },
      {
        id: "msg_1034_2",
        author: "operator",
        body: "That’s great to hear — thank you for the note. I’ve marked this resolved.",
        timestamp: "Jul 31",
      },
    ],
  },
];

export const BACKOFFICE_ACTIVITY: ActivityItem[] = [
  {
    id: "act_1",
    tone: "sage",
    title: "Issue exported",
    detail: "Amira Diallo · Issue 02 · PDF",
    time: "4 min ago",
  },
  {
    id: "act_2",
    tone: "red",
    title: "Generation needs attention",
    detail: "Maya Chen · Cast references · 1 retry",
    time: "11 min ago",
  },
  {
    id: "act_3",
    tone: "gold",
    title: "New Studio plan",
    detail: "Jules Carter · 2,500 credits",
    time: "18 min ago",
  },
  {
    id: "act_4",
    tone: "blue",
    title: "Project created",
    detail: "Oliver Grant · The Glass Orchard",
    time: "26 min ago",
  },
  {
    id: "act_5",
    tone: "ink",
    title: "Support note added",
    detail: "Rowan Brooks · Credit ledger review",
    time: "36 min ago",
  },
];

export const USAGE_SERIES: Record<"7d" | "30d" | "90d", SeriesPoint[]> = {
  "7d": [
    { label: "Mon", value: 42, secondary: 27 },
    { label: "Tue", value: 56, secondary: 31 },
    { label: "Wed", value: 64, secondary: 38 },
    { label: "Thu", value: 58, secondary: 35 },
    { label: "Fri", value: 76, secondary: 48 },
    { label: "Sat", value: 82, secondary: 55 },
    { label: "Sun", value: 71, secondary: 46 },
  ],
  "30d": [
    { label: "Jul 05", value: 36, secondary: 24 },
    { label: "Jul 09", value: 48, secondary: 28 },
    { label: "Jul 13", value: 43, secondary: 31 },
    { label: "Jul 17", value: 62, secondary: 38 },
    { label: "Jul 21", value: 58, secondary: 35 },
    { label: "Jul 25", value: 74, secondary: 49 },
    { label: "Jul 29", value: 81, secondary: 57 },
    { label: "Aug 01", value: 71, secondary: 46 },
  ],
  "90d": [
    { label: "Jun 03", value: 22, secondary: 14 },
    { label: "Jun 15", value: 31, secondary: 21 },
    { label: "Jun 27", value: 38, secondary: 24 },
    { label: "Jul 09", value: 48, secondary: 28 },
    { label: "Jul 21", value: 58, secondary: 35 },
    { label: "Aug 01", value: 71, secondary: 46 },
  ],
};

export const ANALYTICS_SERIES: SeriesPoint[] = [
  { label: "Jun 03", value: 22, secondary: 14 },
  { label: "Jun 10", value: 27, secondary: 18 },
  { label: "Jun 17", value: 36, secondary: 21 },
  { label: "Jun 24", value: 42, secondary: 26 },
  { label: "Jul 01", value: 48, secondary: 31 },
  { label: "Jul 08", value: 44, secondary: 29 },
  { label: "Jul 15", value: 58, secondary: 35 },
  { label: "Jul 22", value: 67, secondary: 43 },
  { label: "Jul 29", value: 81, secondary: 57 },
];

export const MODEL_SPEND = [
  { model: "Gemini 3 Pro Image", alias: "image-balanced", calls: 842, spend: 184.4, share: 54, tone: "red" as const },
  { model: "GPT Image 2", alias: "image-quality", calls: 268, spend: 96.2, share: 28, tone: "gold" as const },
  { model: "Gemini 2.5 Flash", alias: "text-balanced", calls: 1194, spend: 41.6, share: 12, tone: "blue" as const },
  { model: "Claude Sonnet", alias: "text-quality", calls: 136, spend: 19.8, share: 6, tone: "sage" as const },
];

export const FUNNEL_STEPS = [
  { label: "Created account", value: 1284, percent: 100 },
  { label: "Started a project", value: 964, percent: 75 },
  { label: "Approved a look", value: 721, percent: 56 },
  { label: "Drew pages", value: 486, percent: 38 },
  { label: "Exported a book", value: 214, percent: 17 },
];
