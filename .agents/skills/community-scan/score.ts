// Adapted from Falbor, copyright (c) 2026 Falbor, default source license AGPL-3.0.
// Source: /Users/jbuiles/Code/falbor/apps/falbor/app/lib/automation/prompts.ts:4-12,47-71.
// Changes: strict CLI input, exact elapsed days, future-date rejection, standalone output.
// Local private use only in this port. No trademark rights or endorsement are granted.
import process from 'node:process'
import { z } from 'zod'

const factor = z.number().int().min(0).max(100)
const Input = z.strictObject({
  postedAt: z.iso.date().or(z.iso.datetime({ offset: true })).nullable(),
  today: z.iso.date().optional(),
  factors: z.strictObject({
    problemRelevance: factor,
    audienceRelevance: factor,
    productFit: factor,
    intentSignal: factor,
    communityFit: factor,
    participationValue: factor,
  }),
})

try {
  const raw: unknown = JSON.parse(process.argv[2] ?? '')
  const input = Input.parse(raw)
  const now = input.today ? Date.parse(input.today) : Date.now()
  const ageDays = input.postedAt === null ? null : (now - Date.parse(input.postedAt)) / 86_400_000
  if (ageDays !== null && ageDays < 0) throw new Error('postedAt is later than today')
  const recency = ageDays === null ? 40
    : ageDays <= 3 ? 100
    : ageDays <= 7 ? 85
    : ageDays <= 14 ? 70
    : ageDays <= 30 ? 55
    : ageDays <= 60 ? 35
    : ageDays <= 90 ? 20 : 5
  const f = input.factors
  const relevance = Math.round(
    .25 * f.problemRelevance + .15 * f.audienceRelevance + .20 * f.productFit
    + .15 * f.intentSignal + .10 * recency + .10 * f.communityFit + .05 * f.participationValue,
  )
  process.stdout.write(`${JSON.stringify({ ageDays: ageDays ?? 'unknown', recency, relevance })}\n`)
} catch (error) {
  process.stderr.write(`score.ts: ${error instanceof Error ? error.message : 'invalid input'}\n`)
  process.exitCode = 1
}
