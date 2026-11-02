// Functional checks for the actual search script without a browser dependency.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../assets/js/help.js', import.meta.url), 'utf8');
class Element {
  constructor() { this.children = []; this.listeners = {}; this.value = ''; this.textContent = ''; this.hidden = true; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  append(child) { this.children.push(child); }
  replaceChildren() { this.children = []; }
  dispatchEvent(event) { this.listeners[event.type]?.(event); }
}

for (const lang of ['de', 'en']) {
  const pages = JSON.parse(await readFile(new URL(`../public/help-search-${lang}.json`, import.meta.url), 'utf8'));
  const input = new Element();
  const results = new Element();
  const status = new Element();
  const topics = {open: true};
  let scheduled;
  let fail = false;
  let requests = 0;
  const search = {dataset: {index: '/index.json', count: 'results', empty: 'empty', error: 'error'}, querySelector: (selector) => selector === 'input' ? input : selector === 'ul' ? results : status};
  vm.runInNewContext(source, {
    document: {querySelector: (selector) => selector === '.help-topics' ? topics : search, createElement: () => new Element()},
    window: {matchMedia: () => ({matches: true})},
    fetch: async () => { requests++; return {ok: !fail, json: async () => pages}; },
    setTimeout: (callback) => { scheduled = callback; return 1; },
    clearTimeout: () => { scheduled = undefined; },
    Event: class { constructor(type) { this.type = type; } },
  });
  const query = async (value) => {
    input.value = value;
    input.dispatchEvent({type: 'input'});
    if (scheduled) await scheduled();
  };
  assert.equal(topics.open, false, 'Mobile topics should start collapsed');
  fail = true;
  await query('Gemini');
  assert.equal(status.textContent, 'error');
  fail = false;
  await query('Gemini');
  assert.ok(results.children.length > 0);
  assert.equal(requests, 2, 'A failed index request must be retryable');
  const before = requests;
  await query(lang === 'de' ? 'SCHLUSSEL' : 'CREDENTIAL');
  assert.ok(results.children.length > 0, 'Case and German accents should normalize');
  await query(lang === 'de' ? 'gemini kontingent' : 'gemini quota');
  assert.ok(results.children.length > 0, 'All query terms should match');
  assert.ok(results.children.every((item) => item.children[0].href.startsWith(lang === 'de' ? '/de/hilfe/' : '/en/help/')));
  assert.equal(requests, before, 'Successful search index should be reused');
  await query('zzzz-no-such-topic');
  assert.equal(status.textContent, 'empty');
  assert.equal(results.hidden, true);
  await query('Gemini');
  input.listeners.keydown({key: 'Escape'});
  assert.equal(input.value, '');
  assert.equal(results.hidden, true);
  assert.equal(status.textContent, '');
}
console.log('Search checks passed for DE/EN: matching, accents, cache, failure recovery, no results, Escape and mobile topics.');
