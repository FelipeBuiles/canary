import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { gzipSync } from 'node:zlib'

const args = process.argv.slice(2)
const directory = args.includes('--dist') ? args[args.indexOf('--dist') + 1] : 'dist'
const html = await readFile(resolve(directory, 'index.html'), 'utf8')
const files = new Set([...html.matchAll(/<(?:script|link)\b[^>]*\b(?:src|href)="(\/assets\/[^" ]+\.js)"[^>]*>/g)].map(match => match[1]))
if (!files.size) throw new Error('No production entry scripts found; build the frontend first')
let bytes = 0, compressed = 0
for (const file of files) {
  const content = await readFile(resolve(directory, file.slice(1)))
  bytes += content.length
  compressed += gzipSync(content).length
}
console.log(`Startup JavaScript: ${(bytes / 1000).toFixed(1)} KB raw, ${(compressed / 1000).toFixed(1)} KB gzip (${files.size} files)`)
if (!args.includes('--report-only')) {
  if (compressed > 300_000) throw new Error('Startup JavaScript exceeds the 300 KB gzip budget')
  if ([...files].some(file => /\/(?:es|fr|posthog)-/.test(file))) throw new Error('Unused languages or telemetry were added to the critical startup path')
  console.log('Performance budget passed')
}
