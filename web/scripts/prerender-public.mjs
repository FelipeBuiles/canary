import { readFile, writeFile, mkdir, rm } from 'node:fs/promises'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createHash } from 'node:crypto'
import { build } from 'vite'

const output = resolve('node_modules/.tmp/public-render')
const escape = value => String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character])
const json = value => JSON.stringify(value).replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026')
try {
  await build({ build: { ssr: 'src/publicRender.tsx', outDir: output, sourcemap: false } })
  const { publicPages, publicSchema, homePaths, isPublicHome, renderPublicPage } = await import(pathToFileURL(resolve(output, 'publicRender.js')).href)
  const template = await readFile('dist/index.html', 'utf8')
  // Public styles must arrive with HTML, before its lazy route is requested.
  const manifest = JSON.parse(await readFile('dist/.vite/manifest.json', 'utf8'))
  function stylesFor(page) {
    const seen = new Set(), styles = new Set()
    function visit(key) {
      if (seen.has(key)) return
      seen.add(key)
      const chunk = manifest[key]
      if (!chunk) return
      for (const css of chunk.css ?? []) styles.add(css)
      for (const dependency of chunk.imports ?? []) visit(dependency)
    }
    visit(page)
    return [...styles].filter(file => !template.includes(`/${file}`)).map(file => `<link rel="stylesheet" href="/${file}">`).join('')
  }
  const source = resolve('../novel_to_comic/src/novel_to_comic/sample_stories')
  const entries = JSON.parse(await readFile(resolve(source, 'catalog.json'), 'utf8'))
  const stories = await Promise.all(entries.map(async ({ filename, ...entry }) => {
    if (filename !== `${entry.code}.txt`) throw new Error('Invalid public story filename')
    const text = await readFile(resolve(source, filename))
    if (createHash('sha256').update(text).digest('hex') !== entry.sha256) throw new Error(`Unverified sample: ${entry.code}`)
    return { ...entry, words: text.toString().trim().split(/\s+/u).length, source_kind: 'curated' }
  }))
  await mkdir('dist/public', { recursive: true })
  const paths = {}
  for (const [path, metadata] of Object.entries(publicPages)) {
    const bootstrap = { prerendered: true, language: metadata.language, ...(isPublicHome(path) ? { stories } : {}) }
    let markup = await renderPublicPage(path, bootstrap)
    let preloads = ''
    markup = markup.replace(/<link\b[^>]*rel="preload"[^>]*>/g, node => { preloads += node; return '' })
    const url = `https://scenewright.ink${path}`
    const image = 'https://scenewright.ink/marketing/scenewright-social.png'
    let document = template.replace(/<title\b[^>]*>.*?<\/title>/gis, '').replace(/<meta\b[^>]*(?:name|property)="(?:description|robots|og:[^"]+|twitter:[^"]+)"[^>]*>/gi, '').replace(/<link\b[^>]*rel="canonical"[^>]*>/gi, '')
    const head = `<title>${escape(metadata.title)}</title><link rel="canonical" href="${url}">` +
      Object.entries({ description: metadata.description, robots: 'index, follow', 'og:type': 'website', 'og:site_name': 'Scenewright', 'og:title': metadata.title, 'og:description': metadata.description, 'og:url': url, 'og:image': image, 'og:image:width': '1200', 'og:image:height': '630', 'og:image:alt': 'Scenewright — AI comic studio for authors', 'twitter:card': 'summary_large_image', 'twitter:title': metadata.title, 'twitter:description': metadata.description, 'twitter:image': image, 'twitter:image:alt': 'Scenewright — AI comic studio for authors' })
        .map(([key, value]) => `<meta ${key.startsWith('og:') ? 'property' : 'name'}="${key}" content="${escape(value)}">`).join('') +
      (isPublicHome(path) ? [...Object.entries(homePaths), ['x-default', '/']].map(([language, target]) => `<link rel="alternate" hreflang="${language}" href="https://scenewright.ink${target}">`).join('') : '') +
      `<script id="public-schema" type="application/ld+json">${json(publicSchema(path))}</script>`
    const module = isPublicHome(path) ? 'src/pages/HomePage.tsx' : path.startsWith('/legal/') ? { '/legal/terms': 'src/pages/legal/TermsPage.tsx', '/legal/privacy': 'src/pages/legal/PrivacyPage.tsx', '/legal/acceptable-use': 'src/pages/legal/AcceptableUsePage.tsx' }[path] : 'src/pages/ProductPage.tsx'
    document = document.replace('<html lang="en">', `<html lang="${metadata.language}">`).replace('</head>', head + stylesFor(module) + preloads + '</head>')
      .replace('<div id="root"></div>', `<div id="root" data-prerendered="true">${markup}</div><script id="public-bootstrap" type="application/json">${json(bootstrap)}</script>`)
    const file = `public/${path === '/' ? 'home' : path.slice(1).replaceAll('/', '-')}.html`
    await writeFile(resolve('dist', file), document)
    paths[path] = file
  }
  // The SPA shell stays separate so auth/private deep links cannot hydrate a homepage.
  await writeFile('dist/public-pages.json', JSON.stringify(paths, null, 2) + '\n')
  console.log(`Prerendered ${Object.keys(paths).length} public pages from React`)
} finally {
  await rm(output, { recursive: true, force: true })
}
