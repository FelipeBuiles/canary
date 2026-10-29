import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { sha256, readCanary } from './workspace.ts'
import { applyTransition, DeskError, snapshot as readSnapshot, type Snapshot } from './desk.ts'

let root: string
let canaryRoot: string
const path = 'drafts/reddit/example.md'
const markdown = (facts = '[]') => `---\nkind: reply\nchannel: reddit\ntitle: Example\nfacts: ${facts}\nsources: []\ncreated: 2026-10-27\nstatus: draft\n---\n\nShown body\n`

beforeEach(async () => {
  root = mkdtempSync(join(tmpdir(), 'desk-test-'))
  canaryRoot = join(root, 'canary')
  mkdirSync(join(root, 'drafts/reddit'), { recursive: true })
  mkdirSync(join(root, 'knowledge'))
  mkdirSync(canaryRoot)
  writeFileSync(join(root, path), markdown())
  writeFileSync(join(root, 'knowledge/facts.yaml'), '[]')
  writeFileSync(join(root, 'knowledge/canary-manifest.json'), JSON.stringify({ include: ['PRODUCT.md'], exclude: [] }))
  writeFileSync(join(root, 'knowledge/canary.lock.json'), JSON.stringify({ sha: 'fixture', synced: '2026-10-27', files: {} }))
  writeFileSync(join(root, 'knowledge/claims-policy.md'), 'Current claims policy')
})
afterEach(() => { rmSync(root, { recursive: true, force: true }) })
const snapshot = async (): Promise<Snapshot> => readSnapshot({ root, canaryRoot })
async function post(body: unknown) {
  try { const result = applyTransition(body, { root, canaryRoot }); return { status: 200, json: async () => ({ error: '', ...result }) } }
  catch (error) {
    if (!(error instanceof DeskError)) throw error
    return { status: error.status, json: async () => ({ error: error.message }) }
  }
}
async function approval() { const snap = await snapshot(); return { path, revision: snap.drafts[0]!.revision, transition: { to: 'approved' } } }

describe('file-based review desk', () => {
  it('requires renewed review when a cited fact or policy changes', async () => {
    const text = 'A valid quote'
    const fact = { id: 'feature', statement: 'A feature', quote: text, sources: ['PRODUCT.md:1'], marketable: true, verifiedSources: { 'PRODUCT.md': sha256(text) } }
    writeFileSync(join(canaryRoot, 'PRODUCT.md'), text)
    writeFileSync(join(root, 'knowledge/canary.lock.json'), JSON.stringify({ sha: 'fixture', synced: '2026-10-27', files: { 'PRODUCT.md': sha256(text) } }))
    writeFileSync(join(root, 'knowledge/facts.yaml'), JSON.stringify([fact]))
    writeFileSync(join(root, path), markdown('[feature]'))
    expect((await post(await approval())).status).toBe(200)
    writeFileSync(join(root, 'knowledge/facts.yaml'), JSON.stringify([{ ...fact, statement: 'Changed supporting meaning' }]))
    let view = (await snapshot()).drafts[0]!
    expect(view.approvalCurrent).toBe(false)
    expect((await post({ path, revision: view.revision, transition: { to: 'published' } })).status).toBe(409)
    expect((await post(await approval())).status).toBe(200)
    writeFileSync(join(root, 'knowledge/claims-policy.md'), 'New restriction')
    view = (await snapshot()).drafts[0]!
    expect(view.approvalCurrent).toBe(false)
    expect((await post({ path, revision: view.revision, transition: { to: 'published' } })).status).toBe(409)
    expect((await post(await approval())).status).toBe(200)
    view = (await snapshot()).drafts[0]!
    expect((await post({ path, revision: view.revision, transition: { to: 'published' } })).status).toBe(200)
    expect((await post({ path, revision: (await snapshot()).drafts[0]!.revision, transition: { to: 'draft' } })).status).toBe(409)
  })
  it('rejects stale browser content and metadata, then approves the refreshed revision', async () => {
    const request = await approval()
    writeFileSync(join(root, path), markdown().replace('Shown body', 'Unseen body'))
    expect((await post(request)).status).toBe(409)
    expect(readFileSync(join(root, path), 'utf8')).toContain('status: draft')
    expect((await post(await approval())).status).toBe(200)
    const stale = await approval()
    writeFileSync(join(root, path), readFileSync(join(root, path), 'utf8').replace('facts: []', 'facts: [unseen]'))
    expect((await post(stale)).status).toBe(409)
  })
  it('lists reports newest first and treats an unsafe report as a non-blocking warning', async () => {
    mkdirSync(join(root, 'intel/reports'), { recursive: true })
    writeFileSync(join(root, 'intel/reports/2026-10-01-plan.md'), '# October plan\n\nBody')
    writeFileSync(join(root, 'intel/reports/2026-10-27-plan.md'), 'no heading')
    writeFileSync(join(root, 'outside.md'), '# secret')
    symlinkSync(join(root, 'outside.md'), join(root, 'intel/reports/2026-10-28-link.md'))
    const snap = await snapshot()
    expect(snap.reports.map((r) => r.title)).toEqual(['2026-10-27-plan', 'October plan'])
    expect(snap.issues).toContainEqual(expect.objectContaining({ level: 'warn', path: 'intel/reports/2026-10-28-link.md' }))
    expect((await post(await approval())).status).toBe(200)
  })
  it('rejects invalid transition payloads', async () => {
    expect((await post('{')).status).toBe(400)
    expect((await post({ path, revision: 'bad', transition: { to: 'approved' } })).status).toBe(400)
  })
  it('reports malformed YAML/JSON without taking down the server and blocks approval', async () => {
    writeFileSync(join(root, 'knowledge/facts.yaml'), 'facts: [')
    writeFileSync(join(root, 'knowledge/canary.lock.json'), '{')
    writeFileSync(join(root, 'drafts/reddit/broken.md'), '---\ntitle: [\n---\nbody')
    const snap = await snapshot()
    expect(snap.issues.filter(i => i.level === 'error')).toHaveLength(3)
    expect((await post(await approval())).status).toBe(409)
    expect((await snapshot()).drafts).toHaveLength(1)
  })
  it('blocks invalid citations and duplicate ledger ids independently', async () => {
    const text = 'Different content'
    const fact = { id: 'feature', statement: 'A feature', quote: 'A valid quote', sources: ['PRODUCT.md:1'], marketable: true, verifiedSources: { 'PRODUCT.md': sha256(text) } }
    writeFileSync(join(canaryRoot, 'PRODUCT.md'), text)
    writeFileSync(join(root, 'knowledge/canary.lock.json'), JSON.stringify({ sha: 'fixture', synced: '2026-10-27', files: { 'PRODUCT.md': sha256(text) } }))
    writeFileSync(join(root, 'knowledge/facts.yaml'), JSON.stringify([fact]))
    writeFileSync(join(root, path), markdown('[feature]'))
    const quoteFailure = await post(await approval())
    expect(quoteFailure.status).toBe(409)
    expect((await quoteFailure.json()).error).toContain('quote not found')
    const valid = { ...fact, quote: text }
    writeFileSync(join(root, 'knowledge/facts.yaml'), JSON.stringify([valid, valid]))
    const duplicateFailure = await post(await approval())
    expect(duplicateFailure.status).toBe(409)
    expect((await duplicateFailure.json()).error).toContain('duplicate fact ids')
    writeFileSync(join(root, 'knowledge/facts.yaml'), JSON.stringify([valid]))
    expect((await post(await approval())).status).toBe(200)
  })
  it('does not let sync reattest facts and rejects stale ledger snapshots', async () => {
    const original = 'A valid quote'
    const fact = { id: 'feature', statement: 'A feature', quote: original, sources: ['PRODUCT.md:1'], marketable: true, verifiedSources: { 'PRODUCT.md': sha256(original) } }
    writeFileSync(join(canaryRoot, 'PRODUCT.md'), original)
    writeFileSync(join(root, 'knowledge/facts.yaml'), JSON.stringify([fact]))
    const sync = (text: string) => writeFileSync(join(root, 'knowledge/canary.lock.json'), JSON.stringify({ sha: sha256(text), synced: '2026-10-27', files: { 'PRODUCT.md': sha256(text) } }))
    sync(original)
    writeFileSync(join(root, path), markdown('[feature]'))
    const stale = await approval()
    writeFileSync(join(root, 'knowledge/facts.yaml'), JSON.stringify([{ ...fact, statement: 'Unseen changed statement' }]))
    expect((await post(stale)).status).toBe(409)
    const changed = `${original}\nA new limitation`
    writeFileSync(join(canaryRoot, 'PRODUCT.md'), changed)
    sync(changed)
    const drift = await post(await approval())
    expect(drift.status).toBe(409)
    expect((await drift.json()).error).toContain('changed since verification')
    writeFileSync(join(root, 'knowledge/facts.yaml'), JSON.stringify([{ ...fact, verifiedSources: { 'PRODUCT.md': sha256(changed) } }]))
    expect((await post(await approval())).status).toBe(200)
  })
  it('diagnoses missing locks, source membership, and unverified claims', async () => {
    const text = 'A valid quote'
    writeFileSync(join(canaryRoot, 'PRODUCT.md'), text)
    writeFileSync(join(root, 'knowledge/facts.yaml'), JSON.stringify([{ id: 'feature', statement: 'A feature', quote: text, sources: ['PRODUCT.md:1'], marketable: true }]))
    writeFileSync(join(root, path), markdown('[feature]'))
    writeFileSync(join(root, 'knowledge/canary-manifest.json'), JSON.stringify({ include: ['OTHER.md'], exclude: [] }))
    const messages = (await snapshot()).drafts[0]!.issues.map(i => i.message).join('\n')
    expect(messages).toContain('not tracked by the source manifest')
    expect(messages).toContain('missing from the sync lock')
    expect(messages).toContain('no verification attestation')
    expect((await post(await approval())).status).toBe(409)
    rmSync(join(root, 'knowledge/canary.lock.json'))
    expect((await snapshot()).issues.some(i => i.message.includes('lock missing'))).toBe(true)
  })
  it('never reads or writes draft symlinks or follows canary symlinks outside its root', async () => {
    const external = join(root, 'external.md')
    writeFileSync(external, markdown())
    symlinkSync(external, join(root, 'drafts/reddit/link.md'))
    symlinkSync(external, join(canaryRoot, 'PRODUCT.md'))
    const snap = await snapshot()
    expect(readCanary('PRODUCT.md', canaryRoot)).toBeUndefined()
    expect(readCanary('../external.md', canaryRoot)).toBeUndefined()
    expect(snap.drafts.map(d => d.path)).not.toContain('drafts/reddit/link.md')
    expect(snap.issues.some(i => /symlink/i.test(i.message))).toBe(true)
    expect((await post({ path: 'drafts/reddit/link.md', revision: '0'.repeat(64), transition: { to: 'approved' } })).status).toBe(404)
    expect(readFileSync(external, 'utf8')).toBe(markdown())
  })
})
