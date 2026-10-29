import { readFileSync } from 'node:fs'
import { applyTransition, DeskError, snapshot } from '../src/desk.ts'

try {
  const input = JSON.parse(readFileSync(0, 'utf8')) as unknown
  const result = process.argv[2] === 'snapshot' ? snapshot() : process.argv[2] === 'transition' ? applyTransition(input) : undefined
  if (!result) throw new DeskError(400, 'unknown desk command')
  process.stdout.write(JSON.stringify({ ok: true, snapshot: result }))
} catch (error) {
  process.stdout.write(JSON.stringify({ ok: false, status: error instanceof DeskError ? error.status : 503, detail: error instanceof DeskError ? error.message : 'Marketing workspace could not be read. Check its files and permissions.' }))
}
