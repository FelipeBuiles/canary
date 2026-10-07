import sharp from 'sharp'
import { mkdir } from 'node:fs/promises'

// A deterministic brand card, generated as a build asset rather than a runtime request.
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#ece8dc"/>
  <rect x="36" y="36" width="1128" height="558" fill="#f8f5ed" stroke="#1b1c15" stroke-width="6"/>
  <rect x="62" y="62" width="1076" height="98" fill="#b8202b"/>
  <text x="88" y="123" fill="#fffaf0" font-family="sans-serif" font-size="35" font-weight="700">AI COMIC STUDIO FOR AUTHORS</text>
  <text x="84" y="292" fill="#1b1c15" font-family="sans-serif" font-size="108" font-weight="900" letter-spacing="-4">SCENEWRIGHT</text>
  <text x="88" y="365" fill="#1b1c15" font-family="sans-serif" font-size="42" font-weight="600">Your story. Its first comic scene.</text>
  <g fill="none" stroke="#1b1c15" stroke-width="5"><rect x="88" y="411" width="126" height="126"/><rect x="230" y="411" width="126" height="126"/><rect x="372" y="411" width="126" height="126"/></g>
  <path d="M102 523L148 462L200 523Z" fill="#e4b747"/><circle cx="180" cy="440" r="13" fill="#b8202b"/>
  <path d="M250 434H337V470H299L278 490V470H250Z" fill="#e4b747" stroke="#1b1c15" stroke-width="3"/>
  <path d="M396 434H474M396 460H456M396 486H470M396 512H441" stroke="#b8202b" stroke-width="8"/>
  <text x="618" y="462" fill="#1b1c15" font-family="sans-serif" font-size="29">Direct · Review · Export</text>
  <text x="618" y="511" fill="#1b1c15" font-family="sans-serif" font-size="27" font-weight="700">scenewright.ink</text>
</svg>`
await mkdir('dist/marketing', { recursive: true })
await sharp(Buffer.from(svg)).png().toFile('dist/marketing/scenewright-social.png')
