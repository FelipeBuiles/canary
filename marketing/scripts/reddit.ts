// Read-only Reddit Data API client for community-scan. It only requests an app-only token and issues GETs.
// Reddit blocks anonymous and headless reads, and API keys need Reddit's approval (Responsible Builder Policy).
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { ROOT } from '../src/workspace.ts'

const API = 'https://oauth.reddit.com'
const DEFAULT_USER_AGENT = 'script:scenewright-marketing-research:0.1 (read-only)'
const MAX_COMMENTS = 6
const MAX_SEARCH = 25

type Json = Record<string, unknown>
type Get = (path: string, query?: Record<string, string>) => Promise<unknown>

export const BLOCKED_NO_CREDENTIALS =
  'BLOCKED: REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are not set. Reddit approves API access by request ' +
  '(https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy). ' +
  'Until the owner has approved keys in .env, use an owner-saved rules note instead.'

export function parseSubreddit(input: string): string {
  const name = input.trim().replace(/^\/?r\//i, '').replace(/\/+$/, '')
  if (!/^[A-Za-z0-9_]{2,21}$/.test(name)) throw new Error(`not a subreddit name: ${input}`)
  return name
}

export function parseThreadId(url: string): string {
  const u = URL.parse(url)
  if (!u) throw new Error(`not a Reddit thread URL: ${url}`)
  const host = u.hostname.replace(/^(www|old|new|np)\./, '')
  const parts = u.pathname.split('/').filter(Boolean)
  const id = host === 'redd.it' ? parts[0] : host === 'reddit.com' ? parts[parts.indexOf('comments') + 1] : undefined
  if (!id || !/^[a-z0-9]{4,10}$/.test(id) || (host === 'reddit.com' && !parts.includes('comments'))) {
    throw new Error(`not a Reddit thread URL: ${url}`)
  }
  return id
}

const str = (v: unknown) => (typeof v === 'string' ? v : '')
const isoFromUtc = (v: unknown) => (typeof v === 'number' ? new Date(v * 1000).toISOString() : null)
const children = (listing: unknown): Json[] =>
  ((listing as { data?: { children?: { kind: string; data: Json }[] } })?.data?.children ?? []).map((c) => ({ kind: c.kind, ...c.data }))

export function shapeRules(sub: string, rules: unknown, about: unknown) {
  const r = rules as { rules?: Json[] }
  const a = (about as { data?: Json })?.data ?? {}
  return {
    community: `r/${sub}`,
    rulesUrl: `https://www.reddit.com/r/${sub}/about/rules/`,
    over18: a.over18 === true,
    publicDescription: str(a.public_description),
    sidebar: str(a.description),
    rules: (r.rules ?? []).map((rule) => ({ title: str(rule.short_name), appliesTo: str(rule.kind), text: str(rule.description) })),
  }
}

export function shapeThread(response: unknown, maxComments = MAX_COMMENTS) {
  const [postListing, commentListing] = response as [unknown, unknown]
  const post = children(postListing)[0]
  if (!post) throw new Error('thread response had no post')
  const comments = children(commentListing).filter((c) => c.kind === 't1')
  return {
    url: `https://www.reddit.com${str(post.permalink)}`,
    community: `r/${str(post.subreddit)}`,
    title: str(post.title),
    postedAt: isoFromUtc(post.created_utc),
    locked: post.locked === true,
    archived: post.archived === true,
    over18: post.over_18 === true,
    commentCount: typeof post.num_comments === 'number' ? post.num_comments : null,
    body: str(post.selftext),
    moderatorNotes: comments.filter((c) => c.distinguished === 'moderator').map((c) => str(c.body)),
    topComments: comments
      .filter((c) => c.distinguished !== 'moderator')
      .slice(0, maxComments)
      .map((c) => ({ postedAt: isoFromUtc(c.created_utc), score: typeof c.score === 'number' ? c.score : null, body: str(c.body) })),
  }
}

export function shapeSearch(listing: unknown) {
  return children(listing)
    .filter((c) => c.kind === 't3')
    .map((p) => ({
      url: `https://www.reddit.com${str(p.permalink)}`,
      title: str(p.title),
      postedAt: isoFromUtc(p.created_utc),
      commentCount: typeof p.num_comments === 'number' ? p.num_comments : null,
      locked: p.locked === true,
      archived: p.archived === true,
      over18: p.over_18 === true,
    }))
}

async function connect(env: NodeJS.ProcessEnv): Promise<{ get: Get; calls: () => number }> {
  const id = env.REDDIT_CLIENT_ID
  const secret = env.REDDIT_CLIENT_SECRET
  if (!id || !secret) throw new Error(BLOCKED_NO_CREDENTIALS)
  const userAgent = env.REDDIT_USER_AGENT || DEFAULT_USER_AGENT
  let calls = 1
  const tokenResponse = await fetch('https://www.reddit.com/api/v1/access_token', {
    method: 'POST',
    headers: {
      Authorization: `Basic ${Buffer.from(`${id}:${secret}`).toString('base64')}`,
      'Content-Type': 'application/x-www-form-urlencoded',
      'User-Agent': userAgent,
    },
    body: 'grant_type=client_credentials',
  })
  if (!tokenResponse.ok) throw new Error(`token request failed: HTTP ${tokenResponse.status} ${tokenResponse.statusText}`)
  const token = str(((await tokenResponse.json()) as Json).access_token)
  if (!token) throw new Error('token response had no access_token')
  const get: Get = async (path, query = {}) => {
    calls++
    const url = new URL(path, API)
    for (const [k, v] of Object.entries({ raw_json: '1', ...query })) url.searchParams.set(k, v)
    const res = await fetch(url, { headers: { Authorization: `Bearer ${token}`, 'User-Agent': userAgent } })
    if (!res.ok) throw new Error(`GET ${url.pathname} failed: HTTP ${res.status} ${res.statusText}`)
    return res.json()
  }
  return { get, calls: () => calls }
}

const USAGE = `usage:
  tsx scripts/reddit.ts rules <subreddit>
  tsx scripts/reddit.ts thread <thread-url> [comments<=${MAX_COMMENTS}]
  tsx scripts/reddit.ts search <subreddit> <query> [limit<=${MAX_SEARCH}]`

export async function run(args: string[], env: NodeJS.ProcessEnv = process.env): Promise<unknown> {
  const [command, a, b] = args
  const count = (v: string | undefined, max: number) => Math.min(max, Math.max(1, Number(v) || max))
  if (command === 'rules' && a) {
    const sub = parseSubreddit(a)
    const { get, calls } = await connect(env)
    const data = shapeRules(sub, await get(`/r/${sub}/about/rules`), await get(`/r/${sub}/about`))
    return { fetchedAt: new Date().toISOString(), calls: calls(), ...data }
  }
  if (command === 'thread' && a) {
    const id = parseThreadId(a)
    const { get, calls } = await connect(env)
    const data = shapeThread(await get(`/comments/${id}`, { limit: '20', depth: '1', sort: 'top' }), count(b, MAX_COMMENTS))
    return { fetchedAt: new Date().toISOString(), calls: calls(), ...data }
  }
  if (command === 'search' && a && b) {
    const sub = parseSubreddit(a)
    const { get, calls } = await connect(env)
    const limit = String(count(args[3], MAX_SEARCH))
    const results = shapeSearch(await get(`/r/${sub}/search`, { q: b, restrict_sr: '1', sort: 'new', t: 'year', limit }))
    return { fetchedAt: new Date().toISOString(), calls: calls(), community: `r/${sub}`, query: b, results }
  }
  throw new Error(USAGE)
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  const envFile = join(ROOT, '.env')
  if (existsSync(envFile)) process.loadEnvFile(envFile)
  run(process.argv.slice(2)).then(
    (out) => console.log(JSON.stringify(out, null, 2)),
    (e: unknown) => {
      const message = e instanceof Error ? e.message : String(e)
      console.error(message)
      process.exit(message.startsWith('BLOCKED') ? 2 : 1)
    },
  )
}
