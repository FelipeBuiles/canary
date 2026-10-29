import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { syncCanary } from './sync-canary.ts'

let base: string
let root: string
let canaryRoot: string
const git = (...args: string[]) => execFileSync('git', ['-C', canaryRoot, ...args], { encoding: 'utf8' })
const commit = (file: string, text: string) => {
  writeFileSync(join(canaryRoot, file), text)
  git('add', file)
  git('-c', 'user.name=t', '-c', 'user.email=t@example.com', 'commit', '-qm', `edit ${file}`)
}
const outputs = () => [readFileSync(join(root, 'knowledge/canary.lock.json'), 'utf8'), readFileSync(join(root, 'knowledge/canary-changes.md'), 'utf8')]

beforeEach(() => {
  base = mkdtempSync(join(tmpdir(), 'sync-test-'))
  root = join(base, 'workspace')
  canaryRoot = join(base, 'canary')
  mkdirSync(join(root, 'knowledge'), { recursive: true })
  mkdirSync(canaryRoot)
  writeFileSync(join(root, 'knowledge/canary-manifest.json'), JSON.stringify({ include: ['*.md'], exclude: [] }))
  git('init', '-q')
  commit('PRODUCT.md', 'first\n')
})
afterEach(() => rmSync(base, { recursive: true, force: true }))

describe('canary sync', () => {
  it('leaves lock and changelog byte-identical when nothing changed', () => {
    syncCanary({ root, canaryRoot })
    const before = outputs()
    expect(syncCanary({ root, canaryRoot })).toMatch(/unchanged/)
    expect(outputs()).toEqual(before)
  })

  it('rewrites outputs when a tracked file changes or disappears', () => {
    syncCanary({ root, canaryRoot })
    const before = outputs()
    commit('PRODUCT.md', 'second\n')
    syncCanary({ root, canaryRoot })
    expect(outputs()[0]).not.toBe(before[0])
    expect(outputs()[1]).toContain('- PRODUCT.md')
    git('rm', '-q', 'PRODUCT.md')
    commit('OTHER.md', 'other\n')
    syncCanary({ root, canaryRoot })
    expect(outputs()[1]).toContain('- PRODUCT.md (removed)')
  })

  it.each(['knowledge/canary.lock.json', 'knowledge/canary-changes.md'])('refuses a dangling symlink at %s and writes nothing outside', (output) => {
    const outside = join(base, 'outside.txt')
    symlinkSync(outside, join(root, output))
    expect(() => syncCanary({ root, canaryRoot })).toThrow(/symlink/)
    expect(existsSync(outside)).toBe(false)
  })

  it('refuses a symlinked output directory', () => {
    rmSync(join(root, 'knowledge'), { recursive: true })
    mkdirSync(join(base, 'elsewhere'))
    writeFileSync(join(base, 'elsewhere/canary-manifest.json'), JSON.stringify({ include: ['*.md'], exclude: [] }))
    symlinkSync(join(base, 'elsewhere'), join(root, 'knowledge'))
    expect(() => syncCanary({ root, canaryRoot })).toThrow()
    expect(existsSync(join(base, 'elsewhere/canary.lock.json'))).toBe(false)
  })
})
