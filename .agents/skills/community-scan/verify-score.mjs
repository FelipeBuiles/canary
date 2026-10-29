import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(process.argv[2] ?? '.')
const skill = dirname(fileURLToPath(import.meta.url))
const factors = {
  problemRelevance: 100, audienceRelevance: 100, productFit: 100,
  intentSignal: 100, communityFit: 100, participationValue: 100,
}
const run = (raw) => spawnSync(resolve(root, 'node_modules/.bin/tsx'), [resolve(skill, 'score.ts'), raw], {
  cwd: '/', encoding: 'utf8', env: { ...process.env, NODE_PATH: resolve(root, 'node_modules') },
})
const score = (postedAt, f = factors) => {
  const result = run(JSON.stringify({ today: '2026-10-27', postedAt, factors: f }))
  assert.equal(result.status, 0, result.stderr)
  return JSON.parse(result.stdout)
}
assert.deepEqual(score('2026-10-27'), { ageDays: 0, recency: 100, relevance: 100 })
assert.deepEqual(score(null), { ageDays: 'unknown', recency: 40, relevance: 94 })
const now = Date.parse('2026-10-27')
for (const [days, recency] of [[3, 100], [3.01, 85], [7, 85], [7.01, 70], [14, 70], [14.01, 55], [30, 55], [30.01, 35], [60, 35], [60.01, 20], [90, 20], [90.01, 5]]) {
  const result = score(new Date(now - days * 86_400_000).toISOString())
  assert.equal(result.recency, recency, `age ${days}`)
  assert.equal(result.relevance, Math.round(90 + .1 * recency))
}
const zero = Object.fromEntries(Object.keys(factors).map(key => [key, 0]))
assert.equal(score('2026-10-27', zero).relevance, 10)
for (const [key, weight] of Object.entries({ problemRelevance: .25, audienceRelevance: .15, productFit: .20, intentSignal: .15, communityFit: .10, participationValue: .05 })) {
  assert.equal(score(null, { ...zero, [key]: 100 }).relevance, Math.round(4 + 100 * weight), key)
}
for (const raw of [
  'not json', '{}',
  JSON.stringify({ postedAt: '2026-10-28', today: '2026-10-27', factors }),
  JSON.stringify({ postedAt: '2026-02-30', factors }),
  JSON.stringify({ postedAt: null, factors: { ...factors, productFit: -1 } }),
  JSON.stringify({ postedAt: null, factors: { ...factors, productFit: 101 } }),
  JSON.stringify({ postedAt: null, factors: { ...factors, productFit: 1.5 } }),
  JSON.stringify({ postedAt: null, factors: { ...factors, productFit: '100' } }),
]) {
  const result = run(raw)
  assert.equal(result.status, 1, raw)
  assert.equal(result.stdout, '', raw)
  assert.match(result.stderr, /score.ts:/)
}
process.stdout.write('Community scorer CLI passed endpoints, all recency boundaries, every factor weight, unknown date, and invalid-input tests from cwd /.\n')
