import { audit } from '../src/audit.ts'
import { loadCompetitors, loadDrafts, loadFacts, loadLock, loadManifest, loadOpportunities, loadPolicy, readCanary, sha256 } from '../src/workspace.ts'

const drafts = loadDrafts()
const facts = loadFacts()
const lock = loadLock()
const manifest = loadManifest()
const policy = loadPolicy()
const parseErrors = [...drafts.errors, ...facts.errors, ...lock.errors, ...manifest.errors, ...policy.errors, ...loadCompetitors().errors, ...loadOpportunities().errors]

const issues = audit({ drafts: drafts.drafts, facts: facts.facts, policy: policy.policy, lock: lock.lock, manifest: manifest.manifest, parseErrors, readCanary, hash: sha256 })

for (const issue of issues) process.stdout.write(`${issue.level.toUpperCase()} ${issue.path}: ${issue.message}\n`)
const errors = issues.filter((i) => i.level === 'error').length
process.stdout.write(`check: ${drafts.drafts.length} drafts, ${facts.facts.length} facts, ${errors} errors, ${issues.length - errors} warnings\n`)
process.exit(errors ? 1 : 0)
