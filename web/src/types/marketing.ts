export type MarketingStatus = "draft" | "approved" | "published" | "rejected";
export type MarketingTransition =
  | { to: "approved" }
  | { to: "published"; url?: string }
  | { to: "rejected"; reason: string }
  | { to: "draft" };

export type MarketingIssue = { level: "error" | "warn"; path: string; message: string; factId?: string };
export type MarketingFact = { id: string; statement: string; quote: string; sources: string[]; marketable: boolean };
type DraftMeta = {
  kind: string;
  channel: string;
  title: string;
  target?: string;
  facts: string[];
  sources: string[];
  created: string;
} & (
  | { status: "draft" }
  | { status: "approved" }
  | { status: "published"; published: { at: string; url?: string } }
  | { status: "rejected"; reason: string }
);
export type MarketingDraft = {
  path: string;
  body: string;
  meta: DraftMeta;
  revision: string;
  approvalCurrent: boolean;
  issues: MarketingIssue[];
};
export type MarketingSnapshot = {
  drafts: MarketingDraft[];
  reports: { path: string; title: string; body: string }[];
  facts: MarketingFact[];
  issues: MarketingIssue[];
  canarySha?: string;
};
