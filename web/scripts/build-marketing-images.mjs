import { mkdir, writeFile } from 'node:fs/promises'
import sharp from 'sharp'

const files = [
  'cthulhu-page-40.webp', 'elm-and-keep-page-12.webp',
  'janitor-riso-page-01.webp', 'janitor-gouache-page-01.webp', 'janitor-oil-page-01.webp',
  'kaitlin-page-01.webp', 'kaitlin-page-12.webp', 'kaitlin-page-34.webp',
  'scenewright-film-poster.webp',
]
const directory = new URL('../public/marketing/', import.meta.url)
await mkdir(new URL('previews/', directory), { recursive: true })
const manifest = {}
for (const filename of files) {
  const image = sharp(new URL(filename, directory).pathname)
  const { width, height } = await image.metadata()
  if (!width || !height) throw new Error(`Missing image dimensions: ${filename}`)
  const variants = []
  for (const size of [480, 800]) {
    if (size >= width) continue
    const name = filename.replace('.webp', `-${size}.webp`)
    const info = await image.clone().resize({ width: size, withoutEnlargement: true })
      .webp({ quality: 84, effort: 6 }).toFile(new URL(`previews/${name}`, directory).pathname)
    variants.push({ src: `/marketing/previews/${name}`, width: info.width })
  }
  manifest[`/marketing/${filename}`] = { width, height, variants }
}
await writeFile(new URL('../src/assets/marketing-images.json', import.meta.url), JSON.stringify(manifest, null, 2) + '\n')
console.log(`Built responsive previews for ${files.length} marketing images`)
