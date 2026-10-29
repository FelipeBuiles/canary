import { matchesGlob } from 'node:path'
import { approvalIsCurrent, type CanaryManifest, type CanaryLock, type Draft, type Fact } from './domain.ts'
import type { ParseError } from './workspace.ts'

export type Issue = { level: 'error' | 'warn'; path: string; message: string; factId?: string }

export type AuditInput = {
  drafts: Draft[]
  facts: Fact[]
  policy: string
  lock: CanaryLock | undefined
  manifest?: CanaryManifest
  parseErrors: ParseError[]
  readCanary: (path: string) => string | undefined
  hash: (text: string) => string
}

const squash = (text: string) => text.replace(/\s+/g, ' ').trim()

function parseCitation(citation: string): { file: string; start: number; end: number } {
  const [file = '', range = ''] = citation.split(':')
  const [start = 0, end = start] = range.split('-').map(Number)
  return { file, start, end }
}

export function claimIssues(draft: Draft, facts: Fact[]): Issue[] {
  return draft.meta.facts.flatMap((id): Issue[] => {
    const fact = facts.find((f) => f.id === id)
    if (!fact) return [{ level: 'error', path: draft.path, message: `unknown fact id: ${id}` }]
    if (!fact.marketable) return [{ level: 'error', path: draft.path, message: `fact ${id} is internal-only` }]
    return []
  })
}

function factIssues(input: AuditInput): Issue[] {
  const issues: Issue[] = []
  if (new Set(input.facts.map((f) => f.id)).size !== input.facts.length) {
    issues.push({ level: 'error', path: 'knowledge/facts.yaml', message: 'duplicate fact ids' })
  }
  for (const fact of input.facts) {
    const firstIssue = issues.length
    const cited: string[] = []
    for (const citation of fact.sources) {
      const { file, start, end } = parseCitation(citation)
      if (input.manifest && (!input.manifest.include.some((glob) => matchesGlob(file, glob)) || input.manifest.exclude.some((glob) => matchesGlob(file, glob)))) {
        issues.push({ level: 'warn', path: 'knowledge/facts.yaml', message: `${fact.id}: ${file} is not tracked by the source manifest; update the manifest before review` })
      }
      const text = input.readCanary(file)
      if (text === undefined) {
        issues.push({ level: 'error', path: 'knowledge/facts.yaml', message: `${fact.id}: canary file not found: ${file}` })
        continue
      }
      const lines = text.split('\n')
      if (start < 1 || end < start || end > lines.length) {
        issues.push({ level: 'error', path: 'knowledge/facts.yaml', message: `${fact.id}: ${citation} is outside ${file} (${lines.length} lines)` })
      }
      cited.push(lines.slice(start - 1, end).join('\n'))
      const locked = input.lock?.files[file]
      if (!locked) issues.push({ level: 'warn', path: 'knowledge/facts.yaml', message: `${fact.id}: ${file} is missing from the sync lock/manifest; sync or update the manifest` })
      const verified = fact.verifiedSources?.[file]
      if (!verified) issues.push({ level: 'warn', path: 'knowledge/facts.yaml', message: `${fact.id}: ${file} has no verification attestation; review the claim and record its source hash` })
      else if (verified !== input.hash(text)) issues.push({ level: 'warn', path: 'knowledge/facts.yaml', message: `${fact.id}: ${file} changed since verification; review the claim and renew its source hash` })
      if (locked && locked !== input.hash(text)) {
        issues.push({ level: 'warn', path: 'knowledge/facts.yaml', message: `${fact.id}: ${file} changed since last sync; re-verify` })
      }
    }
    if (!cited.some((block) => squash(block).includes(squash(fact.quote)))) {
      issues.push({ level: 'error', path: 'knowledge/facts.yaml', message: `${fact.id}: quote not found in cited lines` })
    }
    for (let i = firstIssue; i < issues.length; i++) {
      const issue = issues[i]
      if (issue) issue.factId = fact.id
    }
  }

  return issues
}

export function audit(input: AuditInput): Issue[] {
  const ledgerIssues = factIssues(input)
  const draftIssues = input.drafts.flatMap((draft): Issue[] => {
    const historical = draft.meta.status === 'published'
    const issues: Issue[] = []
    if (!approvalIsCurrent(draft, input)) {
      const message = historical
        ? 'published copy or evidence differs from its approval record'
        : 'edited after approval; re-approve before posting'
      issues.push({ level: 'error', path: draft.path, message })
    }
    issues.push(...claimIssues(draft, input.facts))
    for (const issue of ledgerIssues) {
      if (issue.factId && draft.meta.facts.includes(issue.factId)) {
        issues.push({ ...issue, level: 'error', path: draft.path })
      }
    }
    if (!historical) return issues
    return issues.map((issue): Issue => ({ ...issue, level: 'warn', message: `Published history: ${issue.message}` }))
  })
  return [...input.parseErrors.map((e): Issue => ({ level: 'error', ...e })), ...ledgerIssues, ...draftIssues]
}
