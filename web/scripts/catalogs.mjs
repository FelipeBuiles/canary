/** Validate ICU catalogs and extract statically declared t() messages. No runtime scraping. */
import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';
import { parse, TYPE } from '@formatjs/icu-messageformat-parser';
const root = path.resolve(import.meta.dirname, '../src');
const locales = ['en', 'es', 'fr'];
const catalogs = Object.fromEntries(locales.map(locale => [locale, JSON.parse(fs.readFileSync(`${root}/locales/${locale}.json`, 'utf8'))]));
const errors = [];
const used = new Map();
const calls = [];
function files(dir) { return fs.readdirSync(dir, { withFileTypes: true }).flatMap(e => e.isDirectory() ? (['__tests__', 'test', 'locales'].includes(e.name) ? [] : files(path.join(dir, e.name))) : [path.join(dir, e.name)]); }
function literals(node) {
  if (ts.isStringLiteralLike(node)) return [node.text];
  if (ts.isConditionalExpression(node)) return [...literals(node.whenTrue), ...literals(node.whenFalse)];
  return [];
}
for (const file of files(root).filter(f => /\.tsx?$/.test(f))) {
  const ast = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true);
  function visit(node) {
    if (ts.isCallExpression(node) && ['t', 'msg'].includes(node.expression.getText(ast)) && node.arguments.length) {
      for (const message of literals(node.arguments[0])) {
        used.set(message, path.relative(root, file));
        if (node.expression.getText(ast) === 't') calls.push({ message, file, values: node.arguments[1] });
      }
    }
    // Interpolation belongs to ICU, never string replacement after translation.
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)
      && node.expression.name.text === 'replace' && ts.isCallExpression(node.expression.expression)
      && node.expression.expression.expression.getText(ast) === 't') errors.push(`${file}: replace after t(); pass ICU values instead`);
    ts.forEachChild(node, visit);
  }
  visit(ast);
}
// Extraction adds source-first messages and empty target entries. It never invents
// translations, overwrites existing copy, or deletes dynamically referenced labels.
if (process.argv.includes('--extract')) {
  for (const [message] of used) {
    if (!Object.hasOwn(catalogs.en, message)) catalogs.en[message] = message.replaceAll("'", "''");
    for (const locale of locales.slice(1)) if (!Object.hasOwn(catalogs[locale], message)) catalogs[locale][message] = '';
  }
  for (const locale of locales) fs.writeFileSync(`${root}/locales/${locale}.json`, JSON.stringify(Object.fromEntries(Object.entries(catalogs[locale]).sort()), null, 2) + '\n');
}
for (const [message, file] of used) {
  if (!Object.hasOwn(catalogs.en, message)) errors.push(`${file}: missing source message ${JSON.stringify(message)}`);
}
function argumentsOf(nodes, result = new Set()) {
  for (const node of nodes) {
    if ([TYPE.argument, TYPE.number, TYPE.date, TYPE.time, TYPE.select, TYPE.plural].includes(node.type)) result.add(node.value);
    if (node.options) for (const option of Object.values(node.options)) argumentsOf(option.value, result);
  }
  return [...result].sort().join(',');
}
for (const { message, file, values } of calls) {
  if (!Object.hasOwn(catalogs.en, message)) continue;
  try {
    const names = argumentsOf(parse(catalogs.en[message], { ignoreTag: true })).split(',').filter(Boolean);
    if (names.length && !values) errors.push(`${file}: missing ICU values for ${message}`);
    if (values && ts.isObjectLiteralExpression(values) && !values.properties.some(ts.isSpreadAssignment)) {
      const supplied = new Set(values.properties.map(property => property.name?.text));
      for (const name of names) if (!supplied.has(name)) errors.push(`${file}: missing ICU value ${name} for ${message}`);
    }
  } catch { /* The catalog syntax error is reported below. */ }
}
for (const [key, source] of Object.entries(catalogs.en)) {
  let args;
  try { args = argumentsOf(parse(source, { ignoreTag: true })); } catch (e) { errors.push(`en ${key}: ${e.message}`); continue; }
  for (const locale of locales.slice(1)) {
    const value = catalogs[locale][key];
    if (typeof value !== 'string' || (source.trim() && !value.trim())) { errors.push(`${locale}: missing ${key}`); continue; }
    try {
      if (argumentsOf(parse(value, { ignoreTag: true })) !== args) errors.push(`${locale}: placeholder mismatch ${key}`);
    } catch (e) { errors.push(`${locale} ${key}: ${e.message}`); }
  }
}
for (const locale of locales.slice(1)) for (const key of Object.keys(catalogs[locale])) if (!Object.hasOwn(catalogs.en, key)) errors.push(`${locale}: unknown source message ${key}`);

if (errors.length) { console.error(errors.join('\n')); process.exitCode = 1; }
else console.log(`Validated ${Object.keys(catalogs.en).length} messages in ${locales.length} ICU catalogs; ${used.size} static messages checked.`);
