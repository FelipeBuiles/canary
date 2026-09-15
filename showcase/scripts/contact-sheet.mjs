import { createRequire } from 'node:module';
import { readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const sharp = createRequire(new URL('../../web/package.json', import.meta.url))('sharp');
const dir=resolve(dirname(fileURLToPath(import.meta.url)),'../audit-captures');
const files=readdirSync(dir).filter(f=>/^\d+.*\.png$/.test(f)).sort();
const cols=4,w=640,h=400,parts=[];
for(const [i,file] of files.entries()) {
  const x=i%cols*w,y=Math.floor(i/cols)*h;
  parts.push({input:await sharp(resolve(dir,file)).resize(620,349,{fit:'inside'}).toBuffer(),left:x+10,top:y+10});
  parts.push({input:Buffer.from(`<svg width="640" height="40"><rect width="640" height="40" fill="#eeeadd"/><text x="12" y="25" font-family="Arial" font-size="17" fill="#1a1b14">${file.replace('.png','')}</text></svg>`),left:x,top:y+355});
}
await sharp({create:{width:w*cols,height:Math.ceil(files.length/cols)*h,channels:3,background:'#eeeadd'}}).composite(parts).png().toFile(resolve(dir,'contact-sheet.png'));
console.log(`Contact sheet: ${files.length} candidates`);
