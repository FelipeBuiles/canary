import { createHash } from 'node:crypto'
import { z } from 'zod'

const isoDate = z.iso.date().or(z.iso.datetime({ offset: true }))

export const Channel = z.enum([
  'reddit',
  'forum',
  'discord',
  'x',
  'bluesky',
  'blog',
  'newsletter',
  'meta-ads',
  'google-ads',
  'landing',
])
export type Channel = z.infer<typeof Channel>

export const DraftKind = z.enum(['reply', 'post', 'article', 'ad'])

const Approval = z.object({ hash: z.string().length(64), at: isoDate })

const draftBase = {
  kind: DraftKind,
  channel: Channel,
  title: z.string().min(1),
  target: z.url().optional(),
  facts: z.array(z.string()).default([]),
  sources: z.array(z.url()).default([]),
  created: isoDate,
}

export const DraftMeta = z.discriminatedUnion('status', [
  z.object({ ...draftBase, status: z.literal('draft') }),
  z.object({ ...draftBase, status: z.literal('approved'), approval: Approval }),
  z.object({
    ...draftBase,
    status: z.literal('published'),
    approval: Approval,
    published: z.object({ url: z.url().optional(), at: isoDate }),
  }),
  z.object({ ...draftBase, status: z.literal('rejected'), reason: z.string().min(1) }),
])
export type DraftMeta = z.infer<typeof DraftMeta>
export type Draft = { path: string; meta: DraftMeta; body: string }

export const Competitor = z.object({
  name: z.string().min(1),
  url: z.url(),
  category: z.enum(['ai-comic', 'ai-image', 'comic-tooling', 'writing-tool', 'other']),
  pricing: z.string().optional(),
  reviewed: isoDate,
  sources: z.array(z.url()).min(1),
})

export const Opportunity = z.object({
  url: z.url(),
  community: z.string().min(1),
  found: isoDate,
  relevance: z.number().int().min(0).max(100),
  status: z.enum(['new', 'drafted', 'skipped']),
  draft: z.string().optional(),
})

export const Fact = z.object({
  id: z.string().regex(/^[a-z0-9-]+$/),
  statement: z.string().min(1),
  quote: z.string().min(8),
  sources: z.array(z.string().regex(/^[^:]+:\d+(-\d+)?$/, 'canary path:line or path:start-end')).min(1),
  marketable: z.boolean(),
  verifiedSources: z.record(z.string().regex(/^(?!\/)(?!.*(?:^|\/)\.\.(?:\/|$))[^:]+$/), z.string().regex(/^[a-f0-9]{64}$/)).optional(),
})
export type Fact = z.infer<typeof Fact>
export const FactLedger = z.array(Fact)

export const CanaryManifest = z.object({ include: z.array(z.string()).min(1), exclude: z.array(z.string()) })
export type CanaryManifest = z.infer<typeof CanaryManifest>

export const CanaryLock = z.object({
  sha: z.string(),
  synced: isoDate,
  files: z.record(z.string(), z.string()),
})
export type CanaryLock = z.infer<typeof CanaryLock>

export type ApprovalContext = { facts: Fact[]; policy: string }

export function approvalHash(draft: Pick<Draft, 'body' | 'meta'>, context: ApprovalContext): string {
  const { kind, title, channel, target, facts, sources, created } = draft.meta
  return createHash('sha256').update(JSON.stringify([kind, channel, target ?? null, title, facts, sources, created, draft.body.trim(), facts.map(id => context.facts.find(f => f.id === id) ?? null), context.policy])).digest('hex')
}

export function approvalIsCurrent(draft: Draft, context: ApprovalContext): boolean {
  return draft.meta.status === 'draft' || draft.meta.status === 'rejected' || draft.meta.approval.hash === approvalHash(draft, context)
}

export type Transition =
  | { to: 'approved'; at: string }
  | { to: 'published'; at: string; url?: string }
  | { to: 'rejected'; reason: string }
  | { to: 'draft' }

export function transition(draft: Draft, t: Transition, context: ApprovalContext): DraftMeta {
  const { meta } = draft
  const base = {
    kind: meta.kind,
    channel: meta.channel,
    title: meta.title,
    target: meta.target,
    facts: meta.facts,
    sources: meta.sources,
    created: meta.created,
  }
  if (meta.status === 'published') throw new Error('published drafts are history; write a new draft instead')
  switch (t.to) {
    case 'draft':
      return { ...base, status: 'draft' }
    case 'rejected':
      return { ...base, status: 'rejected', reason: t.reason }
    case 'approved':
      return { ...base, status: 'approved', approval: { hash: approvalHash(draft, context), at: t.at } }
    case 'published':
      if (meta.status !== 'approved') throw new Error('only an approved draft can be marked published')
      if (!approvalIsCurrent(draft, context)) throw new Error('draft changed after approval; re-approve first')
      return { ...base, status: 'published', approval: meta.approval, published: { url: t.url, at: t.at } }
    default: {
      const _exhaustive: never = t
      return _exhaustive
    }
  }
}
