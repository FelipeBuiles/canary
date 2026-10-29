import { describe, expect, it } from 'vitest'
import { audit, claimIssues } from './audit.ts'
import { approvalIsCurrent, transition, type Draft, type Fact } from './domain.ts'

const context = { facts: [], policy: 'Current claims policy' }
const draft = (overrides: Partial<Draft> = {}): Draft => ({
  path: 'drafts/reddit/x.md',
  body: 'Scenewright turns a novel into a comic.',
  meta: { kind: 'reply', channel: 'reddit', title: 'Re: novel to comic', facts: [], sources: [], created: '2026-10-27', status: 'draft' },
  ...overrides,
})

function approve(d: Draft): Draft {
  return { ...d, meta: transition(d, { to: 'approved', at: '2026-10-27' }, context) }
}

describe('draft lifecycle', () => {
  it('invalidates approved and published drafts when claim metadata changes', () => {
    const approved = approve(draft())
    const published = { ...approved, meta: transition(approved, { to: 'published', at: '2026-10-28' }, context) }
    for (const reviewed of [approved, published]) {
      for (const edit of [{ facts: ['different'] }, { sources: ['https://example.com'] }, { kind: 'post' as const }, { created: '2026-10-26' }]) {
        expect(approvalIsCurrent({ ...reviewed, meta: { ...reviewed.meta, ...edit } }, context)).toBe(false)
      }
    }
  })
  it('approval binds to content; editing the body invalidates it', () => {
    const approved = approve(draft())
    expect(approvalIsCurrent(approved, context)).toBe(true)
    expect(approvalIsCurrent({ ...approved, body: approved.body + ' Extra copy.' }, context)).toBe(false)
  })
  it('refuses to publish an unapproved or edited draft', () => {
    expect(() => transition(draft(), { to: 'published', at: '2026-10-28' }, context)).toThrow(/approved/)
    const approved = approve(draft())
    expect(() => transition({ ...approved, body: 'changed' }, { to: 'published', at: '2026-10-28' }, context)).toThrow(/re-approve/)
    const published = { ...approved, meta: transition(approved, { to: 'published', at: '2026-10-28', url: 'https://reddit.com/r/x/1' }, context) }
    expect(published.meta.status).toBe('published')
    expect(() => transition(published, { to: 'draft' }, context)).toThrow(/history/)
  })
  it('invalidates approval after policy changes', () => {
    const approved = approve(draft())
    const changed = { ...context, policy: 'A new restriction' }
    expect(approvalIsCurrent(approved, changed)).toBe(false)
    expect(() => transition(approved, { to: 'published', at: '2026-10-28' }, changed)).toThrow(/re-approve/)
  })
})

describe('audit', () => {
  const fact: Fact = { id: 'stages', statement: 'Eight stages', quote: 'an 8-stage pipeline', sources: ['PRODUCT.md:2-3'], marketable: true }
  const canary: Record<string, string> = { 'PRODUCT.md': 'Title\nturns a novel into a comic through\nan 8-stage   pipeline\nfooter' }
  fact.verifiedSources = { 'PRODUCT.md': `h:${canary['PRODUCT.md']}` }
  const base = { policy: context.policy, drafts: [], facts: [fact], lock: { sha: 'fixture', synced: '2026-10-27', files: { 'PRODUCT.md': `h:${canary['PRODUCT.md']}` } }, parseErrors: [], readCanary: (p: string) => canary[p], hash: (t: string) => `h:${t}` }

  it('passes when citations resolve', () => { expect(audit(base)).toEqual([]) })
  it('flags a quote that is not in the cited lines', () => {
    expect(audit({ ...base, facts: [{ ...fact, sources: ['PRODUCT.md:1-2'] }] })).toMatchObject([{ message: expect.stringMatching(/quote not found/) }])
  })
  it('flags citations past the end of the canary file', () => {
    expect(audit({ ...base, facts: [{ ...fact, sources: ['PRODUCT.md:2-9'] }] })[0]).toMatchObject({ level: 'error', message: expect.stringMatching(/outside PRODUCT.md/) })
  })
  it('warns when a cited canary file changed since the last sync', () => {
    const lock = { sha: 'abc', synced: '2026-10-27', files: { 'PRODUCT.md': 'h:old' } }
    expect(audit({ ...base, lock })).toMatchObject([{ level: 'warn' }])
  })
  it('preserves verification drift after the sync lock advances', () => {
    const verified = { ...fact, verifiedSources: { 'PRODUCT.md': 'h:old' } }
    const lock = { sha: 'new', synced: '2026-10-27', files: { 'PRODUCT.md': base.hash(canary['PRODUCT.md']!) } }
    const d = draft({ meta: { ...draft().meta, facts: ['stages'] } })
    expect(audit({ ...base, facts: [verified], lock, drafts: [d] }).some(i => i.path === d.path && i.level === 'error' && /verification/.test(i.message))).toBe(true)
  })
  it('rejects drafts citing unknown or internal-only facts', () => {
    const internal = { ...fact, id: 'provider', marketable: false }
    const d = draft({ meta: { ...draft().meta, facts: ['provider', 'nope'] } })
    expect(audit({ ...base, facts: [fact, internal], drafts: [d] }).map(i => i.message)).toEqual(['fact provider is internal-only', 'unknown fact id: nope'])
    expect(claimIssues(d, [fact, internal])).toHaveLength(2)
  })
  it('reports published evidence changes as historical warnings without requiring reapproval', () => {
    const d = draft({ meta: { ...draft().meta, facts: [fact.id] } })
    const approved = { ...d, meta: transition(d, { to: 'approved', at: '2026-10-27' }, base) }
    const published = { ...approved, meta: transition(approved, { to: 'published', at: '2026-10-28' }, base) }
    for (const changed of [
      { ...base, policy: 'A new policy' },
      { ...base, facts: [{ ...fact, verifiedSources: { 'PRODUCT.md': 'old-hash' } }] },
      { ...base, facts: [] },
      { ...base, facts: [{ ...fact, marketable: false }] },
    ]) {
      const issues = audit({ ...changed, drafts: [published] }).filter(issue => issue.path === published.path)
      expect(issues.length).toBeGreaterThan(0)
      expect(issues.every(issue => issue.level === 'warn')).toBe(true)
      expect(issues.every(issue => !issue.message.includes('re-approve'))).toBe(true)
      expect(() => transition(published, { to: 'approved', at: '2026-10-28' }, changed)).toThrow(/history/)
      expect(audit({ ...changed, drafts: [approved] }).some(issue => issue.path === approved.path && issue.level === 'error')).toBe(true)
    }
  })
  it('rejects an approved draft whose body changed', () => {
    expect(audit({ ...base, drafts: [{ ...approve(draft()), body: 'edited' }] })).toMatchObject([{ level: 'error', message: expect.stringMatching(/re-approve/) }])
  })
})
