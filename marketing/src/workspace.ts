import { createHash } from 'node:crypto'
import { existsSync, lstatSync, readdirSync, readFileSync, realpathSync, writeFileSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { parse as parseYaml, stringify as stringifyYaml } from 'yaml'
import type { z } from 'zod'
import { CanaryLock, CanaryManifest, Competitor, DraftMeta, FactLedger, Opportunity, type Draft, type DraftMeta as DraftMetaT } from './domain.ts'

export const ROOT = resolve(import.meta.dirname, '..')
export const CANARY_ROOT = resolve(process.env.CANARY_ROOT ?? join(ROOT, '..'))

export const PATHS = {
  drafts: 'drafts',
  competitors: 'intel/competitors',
  opportunities: 'intel/opportunities',
  reports: 'intel/reports',
  facts: 'knowledge/facts.yaml',
  policy: 'knowledge/claims-policy.md',
  lock: 'knowledge/canary.lock.json',
  manifest: 'knowledge/canary-manifest.json',
  changes: 'knowledge/canary-changes.md',
} as const

export type ParseError = { path: string; message: string }
export type Parsed<T> = { path: string; data: T; body: string }

export function splitFrontmatter(text: string): { data: unknown; body: string } {
  const match = /^---\n([\s\S]*?)\n---\n?([\s\S]*)$/.exec(text)
  if (!match) return { data: undefined, body: text }
  return { data: parseYaml(match[1] ?? ''), body: match[2] ?? '' }
}

export function joinFrontmatter(meta: DraftMetaT, body: string): string {
  return `---\n${stringifyYaml(meta, { lineWidth: 0 }).trimEnd()}\n---\n\n${body.trim()}\n`
}

function markdownFiles(dir: string, root: string): string[] {
  const abs = join(root, dir)
  if (!existsSync(abs)) return []
  return readdirSync(abs, { recursive: true, encoding: 'utf8' })
    .filter((f) => f.endsWith('.md') && !f.endsWith('README.md'))
    .map((f) => join(dir, f))
    .sort()
}

function loadCollection<S extends z.ZodType>(dir: string, schema: S, root = ROOT) {
  const items: Parsed<z.infer<S>>[] = []
  const errors: ParseError[] = []
  try {
    for (const path of markdownFiles(dir, root)) {
      try {
        const abs = safeFile(root, path)
        const { data, body } = splitFrontmatter(readFileSync(abs, 'utf8'))
        const result = schema.safeParse(data)
        if (result.success) items.push({ path, data: result.data, body })
        else errors.push({ path, message: result.error.issues.map((i) => `${i.path.join('.') || '(frontmatter)'}: ${i.message}`).join('; ') })
      } catch (e) { errors.push({ path, message: String(e) }) }
    }
  } catch (e) { errors.push({ path: dir, message: String(e) }) }
  return { items, errors }
}

export function loadDrafts(root = ROOT) {
  const { items, errors } = loadCollection(PATHS.drafts, DraftMeta, root)
  const drafts: Draft[] = items.map(({ path, data, body }) => ({ path, meta: data, body }))
  return { drafts, errors }
}

export function safeFile(root: string, path: string): string {
  const abs = resolve(root, path)
  const rel = relative(resolve(root), abs)
  if (rel === '..' || rel.startsWith('../') || resolve(root) === abs) throw new Error('path outside workspace')
  let cursor = resolve(root)
  for (const part of rel.split('/')) {
    cursor = join(cursor, part)
    if (lstatSync(cursor).isSymbolicLink()) throw new Error(`symlink is not allowed: ${path}`)
  }
  if (!lstatSync(abs).isFile()) throw new Error(`not a regular file: ${path}`)
  return abs
}

export function saveDraftMeta(path: string, meta: DraftMetaT, expected: Draft, root = ROOT): void {
  const abs = safeFile(root, path)
  const { data, body } = splitFrontmatter(readFileSync(abs, 'utf8'))
  const current = { path, meta: DraftMeta.parse(data), body }
  if (sha256(JSON.stringify(current)) !== sha256(JSON.stringify(expected))) throw new Error('draft changed; refresh before reviewing')
  writeFileSync(abs, joinFrontmatter(meta, body))
}

export type Report = { path: string; title: string; body: string }

export function loadReports(root = ROOT): { reports: Report[]; errors: ParseError[] } {
  const reports: Report[] = []
  const errors: ParseError[] = []
  for (const path of markdownFiles(PATHS.reports, root).reverse()) {
    try {
      const body = readFileSync(safeFile(root, path), 'utf8')
      const title = /^# (.+)$/m.exec(body)?.[1]?.trim() ?? path.split('/').pop()!.replace(/\.md$/, '')
      reports.push({ path, title, body })
    } catch (e) { errors.push({ path, message: String(e) }) }
  }
  return { reports, errors }
}

export const loadCompetitors = () => loadCollection(PATHS.competitors, Competitor)
export const loadOpportunities = () => loadCollection(PATHS.opportunities, Opportunity)

export function loadFacts(root = ROOT) {
  try {
    const result = FactLedger.safeParse(parseYaml(readFileSync(safeFile(root, PATHS.facts), 'utf8')) ?? [])
    if (result.success) return { facts: result.data, errors: [] }
    return { facts: [], errors: [{ path: PATHS.facts, message: result.error.message }] }
  } catch (e) { return { facts: [], errors: [{ path: PATHS.facts, message: String(e) }] } }
}

export function loadLock(root = ROOT): { lock?: CanaryLock; errors: ParseError[] } {
  const abs = join(root, PATHS.lock)
  if (!existsSync(abs)) return { errors: [{ path: PATHS.lock, message: 'canary lock missing; sync canary before review' }] }
  let raw: unknown
  try {
    raw = JSON.parse(readFileSync(safeFile(root, PATHS.lock), 'utf8'))
  } catch (e) {
    return { errors: [{ path: PATHS.lock, message: String(e) }] }
  }
  const result = CanaryLock.safeParse(raw)
  return result.success ? { lock: result.data, errors: [] } : { errors: [{ path: PATHS.lock, message: result.error.message }] }
}

export function loadManifest(root = ROOT): { manifest?: CanaryManifest; errors: ParseError[] } {
  try {
    const raw: unknown = JSON.parse(readFileSync(safeFile(root, PATHS.manifest), 'utf8'))
    const result = CanaryManifest.safeParse(raw)
    return result.success ? { manifest: result.data, errors: [] } : { errors: [{ path: PATHS.manifest, message: result.error.message }] }
  } catch (e) { return { errors: [{ path: PATHS.manifest, message: String(e) }] } }
}

export function readCanary(path: string, root = CANARY_ROOT): string | undefined {
  try {
    const abs = safeFile(root, path)
    const rel = relative(realpathSync(root), realpathSync(abs))
    if (rel === '..' || rel.startsWith('../')) return undefined
    return readFileSync(abs, 'utf8')
  } catch { return undefined }
}

export function loadPolicy(root = ROOT): { policy: string; errors: ParseError[] } {
  try { return { policy: readFileSync(safeFile(root, PATHS.policy), 'utf8'), errors: [] } }
  catch (e) { return { policy: '', errors: [{ path: PATHS.policy, message: String(e) }] } }
}

export const sha256 = (text: string) => createHash('sha256').update(text).digest('hex')
