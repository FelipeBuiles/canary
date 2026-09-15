import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

// Uses an already signed-in Playwright CLI session. Never stores credentials.
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const session = process.env.SHOWCASE_SESSION || 'showcase';
const project = 'a16e7aae-0c91-40e7-9e88-e7afad8e2899';
const source = resolve(root, 'projects/947150d4-7d2f-4726-a018-5539f933ea56/the-call-of-cthulhu');
const captures = resolve(root, 'showcase/audit-captures');
mkdirSync(captures, { recursive: true });
mkdirSync(resolve(root, '.playwright-cli'), { recursive: true });

function inventory(dir) {
  return readdirSync(dir, { withFileTypes: true }).sort((a,b)=>a.name.localeCompare(b.name)).flatMap(e => {
    const path = resolve(dir, e.name);
    if (e.isDirectory()) return inventory(path);
    if (!e.isFile() || e.name === '.DS_Store') return [];
    return [[relative(source, path), createHash('sha256').update(readFileSync(path)).digest('hex')]];
  });
}
const before = inventory(source);
const shared = `
  page.setDefaultTimeout(12000);
  await page.setViewportSize({width:2560,height:1440});
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.unroute('**/api/**');
  await page.route('**/api/**', r => ['GET','HEAD','OPTIONS'].includes(r.request().method()) ? r.continue() : r.abort('blockedbyclient'));
  const base = 'http://127.0.0.1:5173/project/${project}';
  const button = name => page.getByRole('button',{name,exact:true});
  const heading = name => page.getByRole('heading',{name,exact:true});
  const artwork = async name => {
    await page.getByRole('img',{name,exact:true}).waitFor({state:'visible'});
    await page.waitForFunction(name=>[...document.images].some(i=>i.alt===name && i.complete && i.naturalWidth>0 && getComputedStyle(i).opacity==='1' && getComputedStyle(i).visibility==='visible'),name,{timeout:12000});
    await page.getByRole('img',{name,exact:true}).evaluate(i=>i.decode());
  };
  const top = async () => {await page.locator('#main-content').evaluate(e=>e.scrollTop=0);};
  const align = async locator => {await locator.evaluate(e=>e.scrollIntoView({block:'start',behavior:'instant'}));};
  const go = async (route, ready) => {await page.goto(base+route); await ready().waitFor({state:'visible'}); await top();};
  const shot = async name => {
    await page.evaluate(()=>document.fonts.ready);
    await page.waitForFunction(()=>[...document.images].filter(i=>{const r=i.getBoundingClientRect();return r.width>0&&r.height>0&&r.top<innerHeight&&r.bottom>0&&i.checkVisibility({checkVisibilityCSS:true});}).every(i=>i.complete&&i.naturalWidth>0),null,{timeout:12000});
    const exposed = await page.locator('body').innerText();
    if (exposed.includes('/Users/') || /Bearer\\s|@gmail\\.com|SUPABASE_/.test(exposed)) throw new Error('Private or developer content visible; refusing capture');
    await page.screenshot({path:'showcase/audit-captures/'+name+'.png',animations:'disabled',caret:'hide',style:'button[aria-label="Account menu"], a[href="/credits"] {visibility:hidden!important}'});
  };
`;
const groups = {
  story: `
    await page.goto('http://127.0.0.1:5173/');
    await page.getByRole('searchbox',{name:'Find a production'}).fill('The Call of Cthulhu'); await top(); await shot('01-library');
    await go('/story',()=>heading('ADAPTATION BRIEF')); await shot('05-story-brief');
    await page.getByRole('link',{name:'Explore extracted story',exact:true}).click(); await align(heading('Inside your story')); await shot('06-extracted-scenes');
    await button('Characters7').click(); await align(heading('Inside your story')); await shot('07-story-characters');
    await button('Places7').click(); await align(heading('Inside your story')); await shot('27-story-places');
  `,
  styles: `
    await go('/styles',()=>heading('STYLE PROOFS')); await shot('08-style-proofs');
    for(const name of ['Sickly Symbolist Oil','Tiffany Cryptic Glass']) await page.getByRole('article').filter({has:heading(name)}).getByRole('button',{name:'COMPARE',exact:true}).click();
    await align(heading('COMPARE PROOFS')); await shot('09-style-comparison');
    await button('View proof and direction · Sickly Symbolist Oil').click(); await page.getByRole('dialog',{name:'Sickly Symbolist Oil',exact:true}).waitFor(); await shot('10-style-direction-detail');
  `,
  cast: `
    await go('/cast',()=>heading('Meet your cast')); await shot('11-cast-gallery');
    await button('Review & adjust · Henry Anthony Wilcox').click(); await page.getByRole('dialog',{name:'HENRY ANTHONY WILCOX',exact:true}).waitFor(); await shot('12-character-direction');
    await page.getByRole('dialog',{name:'HENRY ANTHONY WILCOX',exact:true}).getByRole('button',{name:'Open image · Febrile Delirium',exact:true}).click(); await page.getByRole('dialog',{name:'Febrile Delirium',exact:true}).waitFor(); await shot('13-alternate-appearance');
    await page.keyboard.press('Escape'); await page.keyboard.press('Escape');
    await align(heading('LOCATION PLATES')); await shot('14-location-plates');
    await button("Review & adjust · R'lyeh, Sunken Corpse-City").click(); await page.getByRole('dialog').waitFor(); await shot('15-location-direction');
    await page.keyboard.press('Escape');
    await button("Review & adjust · Professor Angell's Providence Office").click(); await button('Restore v1').waitFor(); await shot('23-reference-history');
  `,
  pages: `
    await go('/pages?filter=all',()=>button('Open page 1, revision 1')); await shot('02-pages-gallery');
    await button('Open page 1, revision 1').click(); await page.getByRole('dialog',{name:'Page 1 review',exact:true}).waitFor(); await artwork('Complete page 1, render revision 1'); await shot('03-page-detail');
    await button('MAKE CHANGES').click(); await heading('Request changes').waitFor(); await shot('04-page-corrections');
    await go('/pages?page=31&review=checks',()=>page.getByRole('dialog',{name:'Page 31 review',exact:true})); await heading('ISSUE HISTORY').waitFor(); await shot('24-lettering-findings');
    await button('Visual review').click(); await artwork('Drawn page 31, revision 1'); await artwork('Cthulhu Stone Idol'); await shot('25-page-reference-review');
    await go('/pages?page=40&review=visual',()=>page.getByRole('img',{name:'Drawn page 40, revision 1',exact:true})); await artwork('Drawn page 40, revision 1'); await artwork('Cthulhu'); await artwork('Gustaf Johansen'); await shot('26-climax-reference-review');
  `,
  planning: `
    await go('/pages?reading=adaptation',()=>heading('Narrative treatment')); await align(heading('Narrative treatment')); await shot('16-adaptation');
    await align(heading('Adapted beats')); await page.getByText('Lettering & story details',{exact:true}).first().click(); await align(heading('Adapted beats')); await shot('17-adapted-lettering');
    await go('/pages?reading=page-plan',()=>heading('Book rhythm')); await page.getByRole('link',{name:'Jump to page 1',exact:true}).click(); await shot('18-page-plan');
  `,
  reader: `
    await go('/book',()=>button('Read your book')); await page.getByRole('link',{name:'DOWNLOAD PDF',exact:true}).waitFor(); await page.getByText('44 pages ready',{exact:true}).waitFor(); await shot('19-book-export-ready');
    await button('Read your book').click(); await page.getByRole('dialog',{name:'Book reader',exact:true}).waitFor();
    const slider=page.getByRole('slider',{name:'Jump to page',exact:true});
    for(const [index,file] of [[1,'20-reader-page02'],[39,'21-reader-page40'],[40,'22-reader-page41']]) {await slider.fill(String(index)); await artwork('Page '+(index+1)+' — Page '+(index+1)); await shot(file);}
  `,
};
const selected = process.argv.slice(2);
const names = selected.length ? selected : Object.keys(groups);
const completedGroups = [];
for (const name of names) {
  if (!groups[name]) throw new Error(`Unknown group: ${name}`);
  const file = resolve(root, '.playwright-cli/showcase-capture-step.js');
  writeFileSync(file, `async page => {${shared}\n${groups[name]}\n}`);
  const result = spawnSync(resolve(root,'node_modules/.bin/playwright-cli'), [`-s=${session}`,'run-code',`--filename=${file}`], {cwd:root,encoding:'utf8',timeout:120000});
  if(result.status!==0 || /### Error/.test(result.stdout || '')) {
    console.error(result.stdout, result.stderr); process.exitCode=1; break;
  }
  console.log(`Captured ${name}`);
  completedGroups.push(name);
}
const after=inventory(source);
const unchanged=JSON.stringify(before)===JSON.stringify(after);
writeFileSync(resolve(captures,'capture-verification.json'),JSON.stringify({viewport:{width:2560,height:1440},projectId:project,requestedGroups:names,completedGroups,complete:completedGroups.length===names.length,sourceFilesChecked:before.length,sourceUnchanged:unchanged,sourceDigest:createHash('sha256').update(JSON.stringify(before)).digest('hex'),capturedAt:new Date().toISOString()},null,2)+'\n');
if(!unchanged) {console.error('Source changed during capture; investigate concurrent activity before claiming an unchanged run.');process.exitCode=1;}
console.log(`Source verification: ${before.length} files, ${unchanged?'unchanged':'changed'}`);
