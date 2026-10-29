import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { z } from 'zod'
import { ROOT, splitFrontmatter } from './workspace.ts'

const skills = join(ROOT, '..', '.agents/skills')
const advertised = ['community-scan', 'competitor-intel', 'ai-visibility', 'content-seo', 'ad-creative', 'growth-analytics', 'product-facts', 'marketing-plan']
const Skill = z.object({ name: z.string().min(1), description: z.string().min(20) })

describe('installed marketing workflows', () => {
  it('loads each advertised skill with its discoverable name and instructions', () => {
    for (const name of advertised) {
      const text = readFileSync(join(skills, name, 'SKILL.md'), 'utf8')
      const { data, body } = splitFrontmatter(text)
      expect(Skill.parse(data).name).toBe(name)
      expect(body).toContain('npm run check')
    }
  })

  it('resolves the documented community scorer command', () => {
    const text = readFileSync(join(skills, 'community-scan/references/rubric.md'), 'utf8')
    expect(text).toContain('node "$SKILL/verify-score.mjs" "$ROOT"')
    expect(existsSync(join(skills, 'community-scan/verify-score.mjs'))).toBe(true)
  })

  it('keeps the Google ad example within limits and discloses AI in every description', () => {
    const text = readFileSync(join(skills, 'ad-creative/SKILL.md'), 'utf8')
    const json = /```json\s*([\s\S]*?)```/.exec(text)?.[1]
    if (!json) throw new Error('Google RSA example is missing')
    const ad = z.object({
      headlines: z.array(z.string().min(1).max(30)).min(3).max(15),
      descriptions: z.array(z.string().min(1).max(90).regex(/AI-assisted/i)).min(2).max(4),
    }).parse(JSON.parse(json))
    expect(new Set(ad.headlines).size).toBe(ad.headlines.length)
  })

  it('resolves local Markdown reference links', () => {
    for (const name of advertised) {
      const directory = join(skills, name)
      for (const file of readdirSync(directory, { recursive: true, encoding: 'utf8' }).filter((f) => f.endsWith('.md'))) {
        const absolute = join(directory, file)
        const text = readFileSync(absolute, 'utf8')
        for (const match of text.matchAll(/\[[^\]]*\]\(([^)]+)\)/g)) {
          const href = match[1]?.split('#')[0]
          if (!href || /^[a-z]+:\/\//i.test(href)) continue
          expect(existsSync(resolve(dirname(absolute), href)), `${name}/${file} links to missing ${href}`).toBe(true)
        }
      }
    }
  })
})
