import { describe, expect, it } from 'vitest'
import { BLOCKED_NO_CREDENTIALS, parseSubreddit, parseThreadId, run, shapeRules, shapeSearch, shapeThread } from './reddit.ts'

describe('reddit read-only client', () => {
  it('reports BLOCKED without credentials and makes no request', async () => {
    await expect(run(['rules', 'WritingWithAI'], {})).rejects.toThrow(BLOCKED_NO_CREDENTIALS)
  })

  it('rejects unknown commands with usage', async () => {
    await expect(run(['post', 'WritingWithAI'], {})).rejects.toThrow(/usage:/)
  })

  it('normalizes subreddit names and refuses anything else', () => {
    expect(parseSubreddit('r/WritingWithAI/')).toBe('WritingWithAI')
    expect(() => parseSubreddit('../api/v1/me')).toThrow()
  })

  it('extracts thread ids from reddit, old.reddit, and redd.it URLs', () => {
    expect(parseThreadId('https://www.reddit.com/r/ComicWriting/comments/1wtot9i/using_ai/?utm_source=x#c')).toBe('1wtot9i')
    expect(parseThreadId('https://old.reddit.com/r/x/comments/abc123/')).toBe('abc123')
    expect(parseThreadId('https://redd.it/abc123')).toBe('abc123')
    expect(() => parseThreadId('https://www.reddit.com/r/x/about/rules/')).toThrow()
    expect(() => parseThreadId('https://example.com/r/x/comments/abc123/')).toThrow()
  })

  it('keeps rule text verbatim', () => {
    const shaped = shapeRules(
      'WritingWithAI',
      { rules: [{ short_name: 'No spam', kind: 'all', description: 'Tools go in the weekly thread.' }] },
      { data: { over18: false, public_description: 'Writers using AI', description: 'Sidebar' } },
    )
    expect(shaped.rules).toEqual([{ title: 'No spam', appliesTo: 'all', text: 'Tools go in the weekly thread.' }])
    expect(shaped.rulesUrl).toBe('https://www.reddit.com/r/WritingWithAI/about/rules/')
  })

  it('separates moderator notes from capped top comments and drops author names', () => {
    const post = { kind: 't3', data: { permalink: '/r/x/comments/abc123/t/', subreddit: 'x', title: 'T', created_utc: 1767225600, locked: false, num_comments: 3, selftext: 'body', author: 'someone' } }
    const comment = (body: string, distinguished: string | null = null) => ({ kind: 't1', data: { body, distinguished, score: 2, created_utc: 1767225600, author: 'someone' } })
    const shaped = shapeThread(
      [{ data: { children: [post] } }, { data: { children: [comment('rule reminder', 'moderator'), comment('a'), comment('b'), { kind: 'more', data: {} }] } }],
      1,
    )
    expect(shaped.postedAt).toBe('2026-01-01T00:00:00.000Z')
    expect(shaped.moderatorNotes).toEqual(['rule reminder'])
    expect(shaped.topComments).toEqual([{ postedAt: '2026-01-01T00:00:00.000Z', score: 2, body: 'a' }])
    expect(JSON.stringify(shaped)).not.toContain('someone')
  })

  it('keeps only posts from search listings', () => {
    const results = shapeSearch({ data: { children: [{ kind: 't3', data: { permalink: '/r/x/comments/abc123/t/', title: 'T' } }, { kind: 't5', data: {} }] } })
    expect(results.map((r) => r.url)).toEqual(['https://www.reddit.com/r/x/comments/abc123/t/'])
  })
})
