import { z } from 'zod'
import type { MarketingSnapshot } from '../../web/src/types/marketing.ts'
import { audit, type Issue } from './audit.ts'
import { approvalIsCurrent, transition, type Draft, type Fact, type Transition } from './domain.ts'
import { CANARY_ROOT, ROOT, loadDrafts, loadFacts, loadLock, loadManifest, loadPolicy, loadReports, readCanary, saveDraftMeta, sha256, type Report } from './workspace.ts'

export type DraftView = Draft & { revision: string; approvalCurrent: boolean; issues: Issue[] }
export type Snapshot = { drafts: DraftView[]; reports: Report[]; facts: Fact[]; issues: Issue[]; canarySha?: string }
export type WorkspaceOptions = { root?: string; canaryRoot?: string }

export const TransitionRequest = z.object({
  path: z.string().max(1024),
  revision: z.string().regex(/^[a-f0-9]{64}$/),
  transition: z.discriminatedUnion('to', [
    z.object({ to: z.literal('approved') }),
    z.object({ to: z.literal('published'), url: z.httpUrl().optional() }),
    z.object({ to: z.literal('rejected'), reason: z.string().trim().min(1).max(8192) }),
    z.object({ to: z.literal('draft') }),
  ]),
})

export class DeskError extends Error {
  constructor(readonly status: number, message: string) { super(message) }
}

function readWorkspace({ root = ROOT, canaryRoot = CANARY_ROOT }: WorkspaceOptions) {
  const drafts = loadDrafts(root)
  const facts = loadFacts(root)
  const lock = loadLock(root)
  const manifest = loadManifest(root)
  const policy = loadPolicy(root)
  const context = { facts: facts.facts, policy: policy.policy }
  const issues = audit({
    drafts: drafts.drafts,
    ...context,
    lock: lock.lock,
    manifest: manifest.manifest,
    parseErrors: [...drafts.errors, ...facts.errors, ...lock.errors, ...manifest.errors, ...policy.errors],
    readCanary: (path) => readCanary(path, canaryRoot),
    hash: sha256,
  })
  const reports = loadReports(root)
  const snapshot: Snapshot = {
    drafts: drafts.drafts.map((d) => ({
      ...d,
      revision: sha256(JSON.stringify([d, context, issues, lock.lock, manifest.manifest])),
      approvalCurrent: approvalIsCurrent(d, context),
      issues: issues.filter((i) => i.path === d.path),
    })),
    reports: reports.reports,
    facts: facts.facts,
    issues: [
      ...issues.filter((i) => !drafts.drafts.some((d) => d.path === i.path)),
      ...reports.errors.map((e): Issue => ({ level: 'warn', path: e.path, message: `report unreadable: ${e.message}` })),
    ],
    canarySha: lock.lock?.sha,
  } satisfies MarketingSnapshot
  return { snapshot, context }
}

export function snapshot(options: WorkspaceOptions = {}): Snapshot {
  return readWorkspace(options).snapshot
}

function stamp(t: z.infer<typeof TransitionRequest>['transition'], at: string): Transition {
  switch (t.to) {
    case 'approved': return { to: 'approved', at }
    case 'published': return { to: 'published', at, url: t.url }
    default: return t
  }
}

export function applyTransition(input: unknown, options: WorkspaceOptions = {}): Snapshot {
  const parsed = TransitionRequest.safeParse(input)
  if (!parsed.success) throw new DeskError(400, parsed.error.message)
  const { snapshot: snap, context } = readWorkspace(options)
  const view = snap.drafts.find((d) => d.path === parsed.data.path)
  if (!view) throw new DeskError(404, `no draft at ${parsed.data.path}`)
  if (view.revision !== parsed.data.revision) throw new DeskError(409, 'workspace changed; refresh and review before continuing')
  const { revision: _revision, approvalCurrent: _current, issues: _issues, ...draft } = view
  const t = parsed.data.transition
  const blocking = t.to === 'approved' || t.to === 'published'
    ? [...snap.issues.filter((i) => i.level === 'error'), ...view.issues.filter((i) => i.level === 'error' && !i.message.startsWith('edited after approval'))]
    : []
  if (blocking.length) throw new DeskError(409, `cannot ${t.to}: ${blocking.map((i) => i.message).join('; ')}`)
  try {
    const meta = transition(draft, stamp(t, new Date().toISOString()), context)
    saveDraftMeta(draft.path, meta, draft, options.root)
  } catch (e) { throw new DeskError(409, e instanceof Error ? e.message : String(e)) }
  return snapshot(options)
}
